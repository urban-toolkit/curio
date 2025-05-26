import os
from utk_curio import curio

def main():
    # Block dev-only flags unless explicitly enabled
    if not os.getenv("CURIO_DEV"):
        os.environ["CURIO_NO_DEV"] = "1"
    
    # Run the main logic
    curio.main()