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
                    if highest_utilization > 0.8:
                        target_cpu = cpu_limit + 0.5 if cpu_utilization > 0.8 else cpu_limit
                        target_memory = memory_limit + 256.0 if memory_utilization > 0.8 else memory_limit
                        target_bandwidth = bw_limit + 20.0 if bw_utilization >0.8 else bw_limit

                        bid = min(budget, self.agent.base_bid * 1.5)
                        print(f"[{self.agent.name}] HIGH STRESS! Requesting CPU: {target_cpu}, MEM: {target_memory}Mi, BW: {target_bandwidth}Mbps. Bidding {bid}.")
                    
                    elif highest_utilization < 0.4:
                        target_cpu = cpu_limit
                        target_memory = memory_limit
                        target_bandwidth = bw_limit
                        bid = min(budget, self.agent.base_bid * 0.1)
                        print(f"[{self.agent.name}] LOW STRESS. Maintaining targets. Bidding {bid}.")
                    else:
                        target_cpu = cpu_limit
                        target_memory = memory_limit
                        target_bandwidth = bw_limit
                        bid = min(budget, self.agent.base_bid)
                        print(f"[{self.agent.name}] COMFORTABLE. Maintaining targets. Bidding {bid}.")
                    
                    reply = Message(to=str(msg.sender))
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "bid" : bid,
                        "cpu_target" : target_cpu,
                        "cpu_limit" : cpu_limit,
                        "memory_target" : target_memory,
                        "memory_limit" : memory_limit,
                        "bw_target" : target_bandwidth,
                        "bw_limtit" : bw_limit,
                        "upf_target" : self.agent.upf_target
                    }) 

                    await self.send(reply)

                if msg.get_metadata("performative") == "accept-proposal":
                    msg_data = json.loads(msg.body)
                    print(f"[{self.agent.name}] Bid accepted. Value to pay: {msg_data['value']}.")
                    self.agent.cpu_limit = msg_data["new_cpu"]
                    self.agent.memory_limit = msg_data["new_memory"]
                    self.agent.bandwidth_limit = msg_data["new_badnwidth"]
                    self.agent.budget -= msg_data['value']
                if msg.get_metadata("performative") == "reject-proposal":
                    msg_data = json.loads(msg.body)
                    self.agent.cpu_limit = msg_data["new_cpu"]
                    self.agent.memory_limit = msg_data["new_memory"]
                    self.agent.bandwidth_limit = msg_data["new_badnwidth"]
                    print(f"[{self.agent.name}] Bid rejected. CPU reduced to: {self.agent.cpu_limit}. MEM reduced to: {self.agent.memory_limit}Mib. BW reduced to: {self.agent.bandwidth_limit}Mbps.")
    class ResourceMonitoring(PeriodicBehaviour):
        async def on_start(self):
            print("[MONITORING] Starting resource monitoring behavior (runs every 5 seconds).")
        async def run(self):
            upf_name = self.agent.upf_target
            
            cpu_usage = self.agent.prometheus_query(upf_name, "cpu")
            memory_usage = self.agent.prometheus_query(upf_name, "memory")
            bandwidth_usage = self.agent.prometheus_query(upf_name, "bandwidth")

            if cpu_usage:
                self.agent.cpu_usage = cpu_usage
            else:
                print("[ERROR] Failed to retrieve cpu usage from Prometheus.")
            
            if memory_usage:
                self.agent.memory_usage = memory_usage
            else:
                print("[ERROR] Failed to retrieve memory usage from Prometheus.")
            
            if bandwidth_usage:
                self.agent.bandwidth_usage = bandwidth_usage
            else:
                print("[ERROR] Failed to retrieve bandwidth usage from Prometheus.")
            

            income = 15.0  # Adjust this to change how fast they recover
            max_budget = 200.0 # Prevent infinite wealth hoarding
            
            self.agent.budget += income
            self.agent.budget = min(self.agent.budget, max_budget)
    def prometheus_query(self, upf_name, resource):
        # Query (Ex: rate(container_cpu_usage_seconds_total{namespace="nrprediger", pod=~"upf-.*", container="upf"}[1m]))
        if resource == "cpu":
            query = self.prom.custom_query(f"rate(container_{resource}_usage_seconds_total{{namespace=\"{NAMESPACE}\", pod=~\"{upf_name}-.*\", container=\"{upf_name}\"}}[1m])")
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
            query = self.prom.custom_query(f"rate(container_network_receive_bytes_total{{namespace=\"{NAMESPACE}\", pod=~\"{upf_name}-.*\"}}[1m])")
            if query:
                resource_usage = query[0]['value'][1]
                return float(resource_usage) / (1024*1024)
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
        self.prom = PrometheusConnect(url ="http://localhost:35235/", disable_ssl=True)
        self.add_behaviour(self.ResourceMonitoring(period=5))
        self.add_behaviour(self.AuctionParticipant())
        return await super().setup()
async def main():
    slice_video_agent = SliceAgent("slice_video_agent@localhost", "password")
    slice_video_agent.base_bid = 85.0
    slice_video_agent.upf_target = "upf"
    slice_video_agent.budget = 200.0

    # Create iperf agents 
    iperf_agents = []
    for i in range(2,10):
        agent_name = f"slice_iperf_agent{i}@localhost"
        agent = SliceAgent(agent_name, "password")
        agent.base_bid = 30.0
        agent.upf_target = f"upf{i}"
        agent.budget = 100.0
        iperf_agents.append(agent)
    
    for agent in iperf_agents:
        await agent.start()
    await slice_video_agent.start()
    print("SliceAgents are running...")


    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Stopping SliceAgents...")
        await slice_video_agent.stop()
        for agent in iperf_agents:
            await agent.stop()

if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=False)