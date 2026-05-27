import json
import resource
import time
import spade
import asyncio
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.behaviour import PeriodicBehaviour
from spade.message import Message
from spade.template import Template
from kubernetes import client, config
from prometheus_api_client import PrometheusConnect

# CONSTANTS
NAMESPACE = "nrprediger"
BASE_BUDGET = 20.0
BASE_INCOME = 2.0
BASE_BID = 10.0

class SliceAgent(Agent):

    class AuctionParticipant(CyclicBehaviour):
        async def on_start(self):
            print(f"[{self.agent.name}] Iniciating listening for Auction...")
        async def run(self):
            msg = await self.receive(timeout=10)

            if msg:
                if msg.get_metadata("performative") == "cfp":
                    print(f"[{self.agent.name}] CFP receveid from Resource Agent. Calculating bid...")
                    # 1. Calculate utilization based on current CPU usage and CPU limit
                    cpu_usage = self.agent.cpu_usage
                    cpu_limit = self.agent.cpu_limit

                    memory_usage = self.agent.memory_usage
                    memory_limit = self.agent.memory_limit

                    bw_usage = self.agent.bandwidth_usage
                    bw_limit = self.agent.bandwidth_limit


                    cpu_utilization = (cpu_usage / cpu_limit ) if cpu_limit > 0.0 else 0.0
                    memory_utilization = (memory_usage / memory_limit) if memory_limit > 0.0 else 0.0
                    bw_utilization = (bw_usage / bw_limit) if bw_limit > 0.0 else 0.0
                    print(f"[{self.agent.name}] Current CPU Utilization: {cpu_utilization:.2%} ({cpu_usage}/{cpu_limit})")
                    print(f"[{self.agent.name}] Current Memory Utilization: {memory_utilization:.2%} ({memory_usage}/{memory_limit})")
                    print(f"[{self.agent.name}] Current Bandwidth Utilization: {bw_utilization:.2%} ({bw_usage}Mbps/{bw_limit}Mbps)")
                    highest_utilization = max(cpu_utilization, memory_utilization, bw_utilization)
                    budget = self.agent.budget

                    # 2. Dynamic Bidding
                    if highest_utilization > 0.6:
                        target_cpu = cpu_limit + 0.2 if cpu_utilization > 0.6 else cpu_limit
                        target_memory = memory_limit + 128.0 if memory_utilization > 0.6 else memory_limit
                        target_bandwidth = bw_limit + 3.0 if bw_utilization >0.6 else bw_limit

                        bid = min(budget, self.agent.base_bid * 1.5)
                        print(f"[{self.agent.name}] HIGH STRESS! Requesting CPU: {target_cpu}, MEM: {target_memory}Mi, BW: {target_bandwidth}Mbps. Bidding {bid}.")
                    elif highest_utilization > 0.4:
                        target_cpu = cpu_limit + 0.1 if cpu_utilization > 0.4 else cpu_limit
                        target_memory = memory_limit
                        target_bandwidth = bw_limit + 0.5 if bw_utilization > 0.4 else bw_limit
                        bid = min(budget, self.agent.base_bid)
                        print(f"[{self.agent.name}] MODERATE STRESS. Requesting CPU: {target_cpu}, MEM: {target_memory}Mi, BW: {target_bandwidth}Mbps. Bidding {bid}.")
                    elif highest_utilization > 0.2:
                        target_cpu = cpu_limit
                        target_memory = memory_limit
                        target_bandwidth = bw_limit
                        bid = min(budget, self.agent.base_bid) 
                        print(f"[{self.agent.name}] COMFORTABLE. Maintaining targets. Bidding {bid}.")
                    else:
                        target_cpu = cpu_limit
                        target_memory = memory_limit
                        target_bandwidth = bw_limit
                        bid = min(budget, self.agent.base_bid * 0.1)
                        print(f"[{self.agent.name}] LOW STRESS. Maintaining targets. Bidding {bid}.")

                    
                    reply = Message(to=str(msg.sender))
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "bid" : bid,
                        "cpu_target" : target_cpu,
                        "cpu_limit" : cpu_limit,
                        "memory_target" : target_memory,
                        "memory_limit" : memory_limit,
                        "memory_usage" : memory_usage,
                        "bw_target" : target_bandwidth,
                        "bw_limit" : bw_limit,
                        "upf_target" : self.agent.upf_target
                    }) 

                    await self.send(reply)

                if msg.get_metadata("performative") == "accept-proposal":
                    msg_data = json.loads(msg.body)
                    print(f"[{self.agent.name}] Bid accepted. Value to pay: {msg_data['value']}.")
                    self.agent.cpu_limit = msg_data["new_cpu"]
                    self.agent.memory_limit = msg_data["new_memory"]
                    self.agent.bandwidth_limit = msg_data["new_bandwidth"]
                    self.agent.budget -= msg_data['value']
                if msg.get_metadata("performative") == "reject-proposal":
                    msg_data = json.loads(msg.body)
                    self.agent.cpu_limit = msg_data["new_cpu"]
                    # self.agent.memory_limit = msg_data["new_memory"]
                    self.agent.bandwidth_limit = msg_data["new_bandwidth"]
                    print(f"[{self.agent.name}] Bid rejected. CPU reduced to: {self.agent.cpu_limit}. BW reduced to: {self.agent.bandwidth_limit}Mbps.")
                
                if msg.get_metadata("performative") == "inform":
                    msg_data = json.loads(msg.body)
                    new_priority = msg_data["new_priority"]
                    self.agent.base_bid = BASE_BID * new_priority
                    self.agent.income = BASE_INCOME * new_priority
                    self.agent.budget = BASE_BUDGET * new_priority
                    print(f"[{self.agent.name}] Received new priority: {new_priority}. Updated base bid: {self.agent.base_bid}, base income: {self.agent.income}, base budget: {self.agent.budget}.")
                

    class ResourceMonitoring(PeriodicBehaviour):
        async def on_start(self):
            print("[MONITORING] Starting resource monitoring behavior (runs every 5 seconds).")
        async def run(self):
            upf_name = self.agent.upf_target
            
            cpu_usage = self.agent.prometheus_query(upf_name, "cpu")
            memory_usage = self.agent.prometheus_query(upf_name, "memory")
            bandwidth_usage = self.agent.prometheus_query(upf_name, "bandwidth")

            if cpu_usage is not None:
                self.agent.cpu_usage = cpu_usage
            else:
                print("[ERROR] Failed to retrieve cpu usage from Prometheus.")
            
            if memory_usage is not None:
                self.agent.memory_usage = memory_usage
            else:
                print("[ERROR] Failed to retrieve memory usage from Prometheus.")
            
            if bandwidth_usage is not None:
                self.agent.bandwidth_usage = bandwidth_usage
            else:
                print("[ERROR] Failed to retrieve bandwidth usage from Prometheus.")
            

            income = self.agent.income  # Adjust this to change how fast they recover
            max_budget = 200.0 # Prevent infinite wealth hoarding
            
            self.agent.budget += income
            self.agent.budget = min(self.agent.budget, max_budget)
    def prometheus_query(self, upf_name, resource):
        # Query (Ex: rate(container_cpu_usage_seconds_total{namespace="nrprediger", pod=~"upf-.*", container="upf"}[1m]))
        if resource == "cpu":
            query = self.prom.custom_query(f"rate(container_{resource}_usage_seconds_total{{namespace=\"{NAMESPACE}\", pod=~\"{upf_name}-.*\", container=\"{upf_name}\"}}[40s])")
            # Print the result
            if query:
                resource_usage = query[0]['value'][1]
                return float(resource_usage)
            else:
                return None
        if resource == "memory":
            query = self.prom.custom_query(f"container_memory_usage_bytes{{namespace=\"{NAMESPACE}\", pod=~\"{upf_name}-.*\", container=\"{upf_name}\"}}")
            if query:
                resource_usage = query[0]['value'][1]
                return float(resource_usage)/(1024*1024)  # Convert to MiB
            else:
                return None
        if resource == "bandwidth":
            query = self.prom.custom_query(f"rate(container_network_receive_bytes_total{{namespace=\"{NAMESPACE}\", pod=~\"{upf_name}-.*\"}}[40s])")
            if query:
                resource_usage = query[0]['value'][1]
                return (float(resource_usage)*8.0) / (1024*1024)
            else:
                return None
    def fetch_initial_limits(self):

        print(f"[{self.name}] Fetching initial CPU configuration from Kubernetes...")
    
        # Connect to K8s API
        config.load_kube_config()
        v1 = client.CoreV1Api()
        
        # Find the pod for this specific UPF
        pods = v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=f"app={self.upf_target}")
        
        if pods.items:
            pod = pods.items[0]
            resources = pod.spec.containers[0].resources
            
            if resources and resources.limits:
                if 'cpu' in resources.limits:
                    cpu_str = resources.limits['cpu']
                    
                    # Convert K8s format (e.g., "500m" or "1") to a Python float (0.5 or 1.0)
                    if cpu_str.endswith('m'):
                        self.cpu_limit = float(cpu_str[:-1]) / 1000.0
                    else:
                        self.cpu_limit = float(cpu_str)
                        
                    print(f"[{self.name}] Successfully loaded initial CPU Limit: {self.cpu_limit}")
                else:
                    print(f"[{self.name}] Pod found, but no CPU limit specified. Defaulting to 1.0")
                    self.cpu_limit = 1.0
                
                if 'memory' in resources.limits:
                    memory_str = resources.limits['memory']
                    if memory_str.endswith('Mi'):
                        self.memory_limit = float(memory_str[:-2])
                    elif memory_str.endswith('Gi'):
                        self.memory_limit = float(memory_str[:-2]) * 1024
                    else:
                        self.memory_limit = float(memory_str) / (1024 * 1024)  # Assume bytes if no unit
                    print(f"[{self.name}] Successfully loaded initial Memory Limit: {self.memory_limit}Mi")
                else:
                    print(f"[{self.name}] Pod found, but no Memory limit specified. Defaulting to 512Mi")
                    self.memory_limit = 512.0
                
                annotations = pod.metadata.annotations or {}
                bw_str = annotations.get("qos.projectcalico.org/egressBandwidth", None)

                if bw_str:
                    if bw_str.endswith('M'):
                        self.bandwidth_limit = float(bw_str[:-1])
                    elif bw_str.endswith('G'):
                        self.bandwidth_limit = float(bw_str[:-1]) * 1024
                else:
                    self.bandwidth_limit = 100.0
                print(f"[{self.name}] Successfully loaded initial Bandwidth Limit: {self.bandwidth_limit}Mbps")
                
    async def setup(self):
        print(f"[{self.name}] Slice Agent starting...")
        self.fetch_initial_limits()

        self.cpu_usage = 0.0
        self.memory_usage = 0.0
        self.bandwidth_usage = 0.0

        self.prom = PrometheusConnect(url ="http://localhost:35235/", disable_ssl=True)
        self.add_behaviour(self.ResourceMonitoring(period=15))
        self.add_behaviour(self.AuctionParticipant())
        return await super().setup()
async def main():
    
    # 1. Define the 1-10 Tiers
    PRIORITY_TIERS = {
        #"emergency_urllc": {"weight": 10.0, "upf": "upf1"}, # Future proofing!
        "gold": {"weight": 8.0, "upf": "upf1"},
        "silver": {"weight": 5.0, "upf": "upf2"},
        "bronze": {"weight": 3.0, "upf": "upf3"},
        #"iot_sensor": {"weight": 1.0, "upf": "upf5"}         # Future proofing!
    }

    # 2. Create Slice Agents for each tier
    slice_agents = []
    
    for tier_name, config in PRIORITY_TIERS.items():
        
        w = config["weight"]
        agent_jid = f"{tier_name}_slice@localhost"
        
        agent = SliceAgent(agent_jid, "password")
        agent.upf_target = config["upf"]
        
        # --- THE FORMULAS ---
        agent.budget = BASE_BUDGET * w
        agent.income = BASE_INCOME * w
        agent.base_bid = BASE_BID * w
        
        slice_agents.append(agent)
        print(f"[{tier_name.upper()}] Initialized -> Income: {agent.income} | Base Bid: {agent.base_bid}")

    # Start the agents
    for agent in slice_agents:
        await agent.start()
        
    print("SliceAgents are running...")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Stopping SliceAgents...")
        for agent in slice_agents:
            await agent.stop()

if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)