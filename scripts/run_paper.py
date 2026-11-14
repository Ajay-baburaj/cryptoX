"""`make paper` — frontend and backend together: serves the dashboard and its live paper-
trading API (order-block strategy, Delta public data, no API key, no real orders) on one port.
"""
from execution.server import main

if __name__ == "__main__":
    main()
