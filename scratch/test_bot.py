import asyncio
import os
import sys

# Add parent directory to path so we can import main
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import PurelinkBot

async def run_test():
    print("--- PURELINK DIAGNOSTIC TEST ---")
    bot = PurelinkBot()
    
    test_url = "http://bit.ly/48JF9bP"
    print(f"INPUT: {test_url}")
    
    print("Resolving... (this mimics exactly what happens in Discord)")
    result = await bot.unwrap_link(test_url)
    
    print(f"OUTPUT: {result}")
    
    if "woot.com" in result and "?" not in result:
        print("\n✅ TEST PASSED: Link was successfully unwrapped and cleaned.")
    else:
        print("\n❌ TEST FAILED: Link was not fully cleaned.")

if __name__ == "__main__":
    asyncio.run(run_test())
