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

class SliceAgent(Agent):

    class AuctionParticipant(CyclicBehaviour):
        async def on_start(self):
            print(f"[{self.agent.name}] Iniciating listening for Auction...")
        async def run(self):
            msg = await self.receive(timeout=10)

            if msg:
                if msg.get_metadata("performative") == "cfp":
                    print(f"[{self.agent.name}] CFP receveid from Resource Agent. Calculating bid...")
                    bid = self.agent.base_bid
                    target_cpu = self.agent.target_cpu
                    current_cpu = self.agent.current_cpu
                    upf = self.agent.upf_target

                    reply = Message(to=str(msg.sender))
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "bid" : bid,
                        "cpu_target" : target_cpu,
                        "current_cpu" : current_cpu,
                        "upf_target" : upf
                    }) 

                    await self.send(reply)
                if msg.get_metadata("performative") == "accept-proposal":
                    msg_data = json.loads(msg.body)
                    print(f"[{self.agent.name}] Bid accepted. Value to pay: {msg_data['value']}.")
                    self.agent.current_cpu = self.agent.target_cpu
                    self.agent.budget -= msg_data['value']
                if msg.get_metadata("performative") == "reject-proposal":
                    msg_data = json.loads(msg.body)
                    self.agent.current_cpu = msg_data["new_cpu"]
                    print(f"[{self.agent.name}] Bid rejected. CPU reduced to: {self.agent.current_cpu}.")

                
    async def setup(self):
        print(f"[{self.name}] Slice Agent starting...")
        self.add_behaviour(self.AuctionParticipant())
        return await super().setup()
async def main():
    slice_video_agent = SliceAgent("slice_video_agent@localhost", "password")
    slice_video_agent.base_bid = 85.0
    slice_video_agent.target_cpu = 1.5
    slice_video_agent.current_cpu = 1.0
    slice_video_agent.upf_target = "upf"
    slice_video_agent.budget = 100.0

    slice_iperf_agent = SliceAgent("slice_iperf_agent@localhost", "password")
    slice_iperf_agent.base_bid = 30.0
    slice_iperf_agent.target_cpu = 1.0
    slice_iperf_agent.current_cpu = 1.0
    slice_iperf_agent.upf_target = "upf2"
    slice_iperf_agent.budget = 50.0




    await slice_iperf_agent.start()
    await slice_video_agent.start()
    print("SliceAgents are running...")


    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Stopping SliceAgents...")
        await slice_video_agent.stop()
        await slice_iperf_agent.stop()

if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=False)