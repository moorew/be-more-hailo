import time
import sys
from core.llm import Brain

def main():
    print("Initializing BMO Brain...")
    try:
        brain = Brain()
    except Exception as e:
        print(f"Failed to initialize Brain: {e}")
        sys.exit(1)
        
    print("BMO is ready! Type 'exit' or 'quit' to stop.")
    print("-" * 50)

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ['exit', 'quit']:
                print("Goodbye!")
                break
            if not user_input.strip():
                continue

            # Measure response time
            start_time = time.time()
            response = brain.think(user_input)
            end_time = time.time()

            print(f"\nBMO: {response}")
            print(f"\n[Response time: {end_time - start_time:.2f} seconds]")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()
