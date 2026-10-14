"""SCOUT's weather-aware routing, as the Weather Routing node runs it.

``calculate_weather_route`` (``weather_routing.py``) builds the road graph of a
roads layer (``road_graph.py``), weighs each road by the weather the package's
graph network predicts on it (``weight_calculation.py``), and finds the routes.
"""

from .weather_routing import calculate_weather_route

__all__ = ["calculate_weather_route"]
