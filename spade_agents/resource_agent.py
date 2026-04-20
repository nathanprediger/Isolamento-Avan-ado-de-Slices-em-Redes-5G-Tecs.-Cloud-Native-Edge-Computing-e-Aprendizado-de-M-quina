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
            try:
                # Load Kubernetes configuration and initialize the API client
                config.load_kube_config()
                self.v1 = client.CoreV1Api()
                print("ResourceAgent started and connected to Kubernetes cluster.")
            except Exception as e:
                print(f"Failed to connect to Kubernetes cluster: {e}")
                await self.agent.stop()
            return await super().on_start()
        async def run(self):
            # The agent will listen for messages containing resource requests
            msg = await self.receive(timeout=5)
            if msg:
                print(f"[RECEIVED] Order received from {msg.sender}: {msg.body}")
                try:
                    payload = json.loads(msg.body)
                    target_upf = payload.get("upf")
                    new_cpu = payload.get("cpu")
                    new_memory = payload.get("memory")
                    new_bandwidth = payload.get("bandwidth")
                    # Update the UPF resource in Kubernetes
                    if target_upf and new_cpu:
                        self.update_pod_cpu(target_upf, new_cpu)
                    if target_upf and new_memory:
                        self.update_pod_memory(target_upf, new_memory)
                    if target_upf and new_bandwidth:
                        self.update_pod_bandwidth(target_upf, new_bandwidth)
                    print(f"[UPDATED] Resource update applied to {target_upf}")
                except json.JSONDecodeError:
                    print("[ERROR]Failed to decode JSON from message body.")
        def update_pod_cpu(self, upf_name, new_cpu):
            try:
                # Fetch the corresponding pod
                pods = self.v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=f"app={upf_name}")
                if pods.items:
                    for pod in pods.items:
                        # Update the CPU resource request/limit
                        pod_name = pod.metadata.name
                        # Create a patch to update the CPU resources
                        patch ={
                            "spec": {
                                "containers": [{
                                    "name": upf_name,  
                                        "resources": {
                                            "limits": {
                                                "cpu": new_cpu
                                            }
                                        }
                                }]
                            }
                        }
                        self.v1.patch_namespaced_pod(name=pod_name, namespace=NAMESPACE, body=patch)
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
                                    "qos.projectcalico.org/ingressBandwidth":new_bandwidth,
                                    "qos.projectcalico.org/egressBandwidth":new_bandwidth
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
                        patch ={
                            "spec": {
                                "containers": [{
                                    "name": upf_name,  
                                        "resources": {
                                            "limits": {
                                                "memory": new_memory
                                            }
                                        }
                                }]
                            }
                        }
                        self.v1.patch_namespaced_pod(name=pod_name, namespace=NAMESPACE, body=patch)
                        print(f"[SUCCESS] Updated MEMORY for pod {pod_name} to {new_memory}")
                else:
                    print(f"[ERROR] No pods found for UPF {upf_name}")
            except Exception as e:
                print(f"[ERROR] Failed to update MEMORY for UPF {upf_name}: {e}")

    class AuctioneerBehavior(PeriodicBehaviour):
        async def on_start(self):
            print("[AUCTION] Initializing auctioneer behavior (runs every 5 seconds).")
            self.auction_id = 0
            # List of auction's participants
            self.slice_agents = ["slice_video_agent@localhost","slice_iperf_agent@localhost"]
        
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
            



            

    async def setup(self):
        print("ResourceAgent starting...")
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