import json
import time
import spade
import asyncio
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.behaviour import PeriodicBehaviour
from spade.message import Message
from spade.template import Template
from kubernetes import client, config

# CONSTANTS
NAMESPACE = "nrprediger"
class ResourceAgent(Agent):
    class ResourceBehavior(CyclicBehaviour):
        async def on_start(self):
            return await super().on_start()
        async def run(self):
            # The agent will listen for messages containing resource requests
            msg = await self.receive(timeout=5)

    class AuctioneerBehavior(PeriodicBehaviour):
        async def on_start(self):
            print("[AUCTION] Initializing auctioneer behavior (runs every 5 seconds).")
            self.auction_id = 0
            # List of auction's participants
            self.slice_agents = ["slice_video_agent@localhost"]
            for i in range(2,10):
                self.slice_agents.append(f"slice_iperf_agent{i}@localhost")
        
        async def run(self):
            self.auction_id += 1
            print(f"[AUCTION] Starting auction #{self.auction_id} for resource allocation.")
            cpu_limit = 1
            memory_limit = 1
            bw_limit = 1

            # Broadcast for auction's participants
            for agent in self.slice_agents:
                msg = Message(to=agent)
                msg.set_metadata("performative", "cfp")
                msg.body = json.dumps({
                    "cpu" : f"{cpu_limit}",
                    "memory" : f"{memory_limit}",
                    "bandwidth" : f"{bw_limit}"
                })
                await self.send(msg)
                print(f"Message sent to {agent}.")
            
            # Collect bids from participants
            print(f"[AUCTION] CFP sent to participants. Awaiting bids...")
            bids = []
            time_limit = 2.0
            start_time = time.time()

            while time.time() - start_time < time_limit:
                time_remaining = time_limit - (time.time() - start_time)
                if time_remaining <= 0:
                    break
                msg = await self.receive(timeout=time_remaining)
                if msg and msg.get_metadata("performative") == "propose":
                    print(f"[AUCTION] Received bid from {msg.sender}: {msg.body}")
                    bids.append(msg)

            print(f"[AUCTION] Auction #{self.auction_id} ended. Total bids received: {len(bids)}")

            if not bids:
                print(f"[AUCTION] No bids received for this auction. Resources remain as it is.")
                return
            
            # Determine the winning bid basen on Vickrey auction rules (highest bidder wins but pays the second-highest bid price)
            
            structured_bids = []
            for bid in bids:
                bid_data = json.loads(bid.body)
                bid_value = float(bid_data["bid"])
                cpu_target = float(bid_data["cpu_target"])
                cpu_limit = float(bid_data["cpu_limit"])
                memory_target = float(bid_data["memory_target"])
                memory_limit = float(bid_data["memory_limit"])
                bw_target = float(bid_data["bw_target"])
                bw_limit = float(bid_data["bw_limit"])
                structured_bids.append({
                    "sender": bid.sender, 
                    "bid": bid_value, 
                    "upf_target": bid_data["upf_target"],
                    "cpu_target": cpu_target,
                    "cpu_limit": cpu_limit,
                    "memory_target": memory_target,
                    "memory_limit": memory_limit,
                    "bw_target": bw_target,
                    "bw_limit": bw_limit
                })
            structured_bids.sort(key=lambda x: x["bid"], reverse=True)
            
            # Announce the result of the auction
            number_of_bids = len(structured_bids)
            # Calculate the quantity of CPU reduction for the loser(s) based on winner's cpu target
            cpu_reduce = (structured_bids[0]["cpu_target"]-structured_bids[0]["cpu_limit"])/(number_of_bids-1) if number_of_bids > 1 else 0
            memory_reduce = (structured_bids[0]["memory_target"]-structured_bids[0]["memory_limit"])/(number_of_bids-1) if number_of_bids > 1 else 0
            bw_reduce = (structured_bids[0]["bw_target"]-structured_bids[0]["bw_limit"])/(number_of_bids-1) if number_of_bids > 1 else 0

            for i, bid in enumerate(structured_bids):
                msg = Message(to=str(bid["sender"]))
                if i == 0:
                    value = structured_bids[1]["bid"] if number_of_bids > 1 else bid["bid"]
                    print(f"[AUCTION] Winner: {bid['sender']} with bid {bid['bid']}. Price to pay: {value}. CPU set to: {bid['cpu_target']}. MEM set to: {bid['memory_target']}.")
                    self.agent.update_pod_cpu(bid["upf_target"], bid["cpu_target"])
                    self.agent.update_pod_memory(bid["upf_target"], bid["memory_target"])
                    self.agent.update_pod_bandwidth(bid["upf_target"], bid["bw_target"])
                    msg.set_metadata("performative", "accept-proposal")
                    msg.body = json.dumps({ "value": value , "new_cpu": bid["cpu_target"], "new_memory": bid["memory_target"], "new_badnwidth": bid["bw_target"]})
                else:
                    new_cpu = max(bid["cpu_limit"]-cpu_reduce, 0.1)
                    new_memory = max(bid["memory_limit"]-memory_reduce, 128.0)
                    new_bandwidth = max(bid["bw_limit"]-bw_reduce, 1.0)
                    print(f"[AUCTION] Loser: {bid['sender']} with bid {bid['bid']}. CPU reduced to: {new_cpu}. MEM reduced to: {new_memory}. BW reduced to: {new_bandwidth}. ")
                    self.agent.update_pod_cpu(bid["upf_target"], new_cpu)
                    self.agent.update_pod_memory(bid["upf_target"], new_memory)
                    self.agent.update_pod_bandwidth(bid["upf_target"], new_bandwidth)

                    msg.set_metadata("performative", "reject-proposal")
                    msg.body = json.dumps({ "new_cpu": new_cpu, "new_memory": new_memory, "new_badnwidth": new_bandwidth})
                    
                await self.send(msg)

                

    def update_pod_cpu(self, upf_name, new_cpu):
        try:
            # Fetch the corresponding pod
            pods = self.v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=f"app={upf_name}")
            if pods.items:
                for pod in pods.items:
                    # Update the CPU resource request/limit
                    pod_name = pod.metadata.name
                    # Create a patch to update the CPU resources
                    patch = [
                        {
                            "op": "replace",
                            "path": "/spec/containers/0/resources/requests/cpu",
                            "value": f"{int(new_cpu * 1000)}m"
                        },
                        {
                            "op": "replace",
                            "path": "/spec/containers/0/resources/limits/cpu",
                            "value": f"{int(new_cpu * 1000)}m"
                        }
                    ]
                    self.v1.patch_namespaced_pod_resize(name=pod_name, namespace=NAMESPACE, body=patch)
                    print(f"[SUCCESS] Updated CPU for pod {pod_name} to {new_cpu}")
            else:
                print(f"[ERROR] No pods found for UPF {upf_name}")
        except Exception as e:
            print(f"[ERROR] Failed to update CPU for UPF {upf_name}: {e}")

    def update_pod_bandwidth(self, upf_name, new_bandwidth):
        try:
            pods = self.v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=f"app={upf_name}")
            if pods.items:
                for pod in pods.items:
                    pod_name = pod.metadata.name
                    patch = {
                        "metadata": {
                            "annotations" : {
                                "qos.projectcalico.org/ingressBandwidth": f"{new_bandwidth}M",
                                "qos.projectcalico.org/egressBandwidth": f"{new_bandwidth}M"
                            }
                        }
                    }
                    self.v1.patch_namespaced_pod(name=pod_name, namespace=NAMESPACE, body=patch)
                    print(f"[SUCCESS] Updated BANDWIDTH for pod {pod_name} to {new_bandwidth}")
            else:
                print(f"[ERROR] No pods found for UPF {upf_name}")
        except Exception as e:
            print(f"[ERROR] Failed to update BANDWIDTH for UPF {upf_name}: {e}")
    
    def update_pod_memory(self, upf_name, new_memory):
        try:
            # Fetch the corresponding pod
            pods = self.v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=f"app={upf_name}")
            if pods.items:
                for pod in pods.items:
                    # Update the CPU resource request/limit
                    pod_name = pod.metadata.name
                    # Create a patch to update the CPU resources
                    patch = [
                        {
                            "op": "replace",
                            "path": "/spec/containers/0/resources/requests/memory",
                            "value": f"{int(new_memory/2)}Mi"
                        },
                        {
                            "op": "replace",
                            "path": "/spec/containers/0/resources/limits/memory",
                            "value": f"{int(new_memory)}Mi"
                        }
                    ]
                    self.v1.patch_namespaced_pod_resize(name=pod_name, namespace=NAMESPACE, body=patch)
                    print(f"[SUCCESS] Updated MEMORY for pod {pod_name} to {new_memory}")
            else:
                print(f"[ERROR] No pods found for UPF {upf_name}")
        except Exception as e:
            print(f"[ERROR] Failed to update MEMORY for UPF {upf_name}: {e}")            

    async def setup(self):
        print("ResourceAgent starting...")
        try:
            # Load Kubernetes configuration and initialize the API client
            config.load_kube_config()
            self.v1 = client.CoreV1Api()
            print("ResourceAgent started and connected to Kubernetes cluster.")
        except Exception as e:
            print(f"Failed to connect to Kubernetes cluster: {e}")
            await self.agent.stop()
        self.add_behaviour(self.ResourceBehavior())
        self.add_behaviour(self.AuctioneerBehavior(period=5))
        return await super().setup() 

async def main():
    resource_agent = ResourceAgent("resource_agent@localhost", "password")
    await resource_agent.start()
    print("ResourceAgent is running...")
    try:
        while resource_agent.is_alive():
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Stopping ResourceAgent...")
    await resource_agent.stop()

if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)