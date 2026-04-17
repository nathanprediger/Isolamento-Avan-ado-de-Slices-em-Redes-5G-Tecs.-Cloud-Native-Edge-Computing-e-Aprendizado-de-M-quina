import json
import spade
import asyncio
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
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
                                    "name": pod_name,  
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


    async def setup(self):
        print("ResourceAgent starting...")
        self.add_behaviour(self.ResourceBehavior())
        return await super().setup()