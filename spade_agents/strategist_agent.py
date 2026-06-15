import json
import yaml
import asyncio
from pydantic import BaseModel, Field
import spade
import os
from dotenv import load_dotenv
from spade.agent import Agent
from spade.message import Message
from spade.behaviour import CyclicBehaviour
from spade_llm import LLMAgent, LLMProvider, ChatAgent
from spade_llm.context import create_user_message, create_system_message, ContextManager
from litellm import acompletion

load_dotenv()
MODEL = "openai/vllm.gpt-oss-20b"
API_KEY = os.getenv("API_KEY")
TEST_CONFIG_PATH = os.getenv("TEST_FILE")
with open(TEST_CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

# ['gold', 'silver', 'bronze'] -> "'gold', 'silver', or 'bronze'"
slice_names = list(config['slices'].keys())
if len(slice_names) > 1:
    valid_slices_str = ", ".join([f"'{s}'" for s in slice_names[:-1]]) + f", or '{slice_names[-1]}'"
else:
    valid_slices_str = f"'{slice_names[0]}'"

class SlicePriorityUpdate(BaseModel):
    # Forces the LLM to output a string, and tells it which strings are allowed
    target_slice: str = Field(description="The exact prefix of the slice: 'gold', 'silver', or 'bronze'")
    
    # Forces the LLM to output a float, and tells it the limits
    new_priority: float = Field(description="The new priority weight for the slice. Use a scale of 1.0 to 10.0.")
    
    # Forces the LLM to explain itself, which is great for your console logs
    reasoning: str = Field(description="A brief explanation of why this weight was assigned based on the network intent.")

class DispatcherAgent(Agent):
    class RouteMessagesBehaviour(CyclicBehaviour):
        async def on_start(self):
            print("🚦 Dispatcher Agent is routing messages...")
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:    
                    clean_json = msg.body.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    policy_updates = json.loads(clean_json)

                    print("🔄 [Dispatcher] Sending new policies to slice agents...")

                    if isinstance(policy_updates, dict):
                            policy_updates = [policy_updates]
                    for update in policy_updates:
                        target_slice = update["target_slice"] + "_slice@localhost"
                        msg = Message(to=str(target_slice))
                        msg.set_metadata("performative", "inform")
                        msg.body = json.dumps({
                            "new_priority": float(update["new_priority"])
                        })
                        await self.send(msg)
                        print(f"📤 Dispatched new priority {update['new_priority']} to {update["target_slice"]} with reasoning: {update['reasoning']}")
                    print("✅ [Dispatcher] All slices updated!\n")
                except Exception as e:
                    print(f"❌ [Dispatcher] Error while sending policies: {e}")

    async def setup(self):
        print("📡 Starting Dispatcher Agent...")
        self.add_behaviour(self.RouteMessagesBehaviour())

        return await super().setup()



async def main():
    print("🚀 Starting Strategist Agent...")
    provider = LLMProvider(
        model=MODEL,
        base_url= 'https://ollama.k8s.inf.ufrgs.br/api',
        api_key=API_KEY,
        temperature=0.01,
    )

    slices_state = ""
    for slice_name, info in config['slices'].items():
        slices_state += f"        - {slice_name} (Default: {info['initial_priority']})\n"
    
    sys_prompt = f"""
        You are an AI 5G Network Strategist orchestrating a Multi-Agent System (MAS). 
        Your job is to translate high-level human intents into economic policies for network slices competing in a resource allocation auction.

        ### THE NETWORK STATE
        You manage active network slices. Their default priority weights are:
        {slices_state}
        ### THE ECONOMIC ENGINE
        You do not allocate CPU or Bandwidth directly. Instead, you control the economic parameters of the MAS. The priority weight (1.0 to 10.0) you assign directly scales a slice's purchasing power in the Vickrey auction using the following formulas:
        - Budget (Wallet Capacity) = {config['bidding']['base_budget']} * new_weight
        - Income (Wealth Regeneration) = {config['bidding']['base_income']} * new_weight
        - Base Bid (Auction Aggressiveness) = {config['bidding']['base_bid']} * new_weight

        ### Requested Output
        When you receive a network intent, you must respond with a JSON array containing one or more objects. Include an object for EVERY slice that needs its priority adjusted.
        [
            {{
                "target_slice": "one of {valid_slices_str}",
                "new_priority": "a float between 1.0 and 10.0",
                "reasoning": "a brief explanation of your decision"
            }}
        ]

        ### YOUR INSTRUCTIONS
        1. Analyze the incoming network intent (e.g., changes in traffic, VIP events, maintenance).
        2. Determine WHICH slices require a priority adjustment to fulfill this intent. You may adjust one, two, or all slices at once.
        3. Calculate a new weight (between 1.0 and 10.0) for each targeted slice. Higher weights grant massive financial dominance; lower weights financially starve the slice.
        4. Provide a brief, logical reasoning for each decision.
        5. You must output ONLY a valid JSON array matching the requested schema. Do not include markdown formatting or conversational filler.
    """
    dispatcher_agent = DispatcherAgent(
        jid="dispatcher_agent@localhost",
        password="password",
    )
    strategist_agent = LLMAgent(
        jid="strategist_agent@localhost",
        password="password",
        provider=provider,
        system_prompt=sys_prompt,
        reply_to="dispatcher_agent@localhost",
    )

    def display_response(message: str, sender: str):
        print(f"\n🤖 Assistant: {message}")
        print("-" * 50)
    user_agent = ChatAgent(
        jid="user_agent@localhost",
        password="password",
        target_agent_jid="strategist_agent@localhost",
    )

    try:
        # Start both agents
        await dispatcher_agent.start()
        await strategist_agent.start()
        await user_agent.start()

        print("✅ Agents started successfully!")
        print("💬 You can now chat with your AI assistant")
        print("Type 'exit' to quit\n")

        # Run interactive chat
        await user_agent.run_interactive(response_timeout=15.0)

    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    finally:
        # Clean up
        await dispatcher_agent.stop()
        await user_agent.stop()
        await strategist_agent.stop()
        print("✅ Agents stopped successfully!")

if __name__ == "__main__":
    spade.run(main())
