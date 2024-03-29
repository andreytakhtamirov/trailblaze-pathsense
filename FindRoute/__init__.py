import logging

import azure.functions as func
from azure.storage.blob import BlobServiceClient
import osmnx as ox
from FindRoute.constants import BLOB_NAME_COORDS_DICTIONARY, CONNECTION_STRING, CONTAINER_NAME, ERROR_MESSAGE_INVALID_COORDINATES, NUM_ROUTES_TO_BUILD

from convert.polyline import route_to_polyline6
from gravel_cycling.weight import cycle_gravel_edge_weight
from metrics.route_parser import metrics_from_route
import json

from util.file_loader import load_pickle
from util.route_builder import RouteBuilder
from util.tile_resolver import geometry_for_coords

BLOB_SERVICE_CLIENT = BlobServiceClient.from_connection_string(
    CONNECTION_STRING)

COORDS_DICT = load_pickle(
    BLOB_SERVICE_CLIENT, CONTAINER_NAME, BLOB_NAME_COORDS_DICTIONARY)


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        req_body = req.get_json()

        origin = req_body['origin']
        destination = req_body['destination']

        origin_lat, origin_lon = origin['latitude'], origin['longitude']
        dest_lat, dest_lon = destination['latitude'], destination['longitude']

        G = geometry_for_coords(BLOB_SERVICE_CLIENT, CONTAINER_NAME, COORDS_DICT, origin_lat,
                                origin_lon, dest_lat, dest_lon)

        if G == None:
            # Graph cannot be resolved (probably invalid coordinates)
            logging.info(
                f'Region not supported: origin: {origin}, destination: {destination}')
            return func.HttpResponse(ERROR_MESSAGE_INVALID_COORDINATES,
                                     status_code=400,
                                     mimetype='text/plain'
                                     )

        start_node = ox.nearest_nodes(
            G, origin_lon, origin_lat)
        end_node = ox.nearest_nodes(
            G, dest_lon, dest_lat)

        route_builder = RouteBuilder(func_weight=cycle_gravel_edge_weight)
        routes = route_builder.create_routes(
            G, start_node, end_node, routes_count=NUM_ROUTES_TO_BUILD)

        route_details_body = []

        for route in routes:
            distance, duration, surface_types_data, highway_types_data = metrics_from_route(
                G, route)

            route_details_body.append({
                "geometry": route_to_polyline6(G, route),
                "duration": duration,
                "distance": distance,
                "metrics": {
                    "surfaceMetrics": surface_types_data,
                    "highwayMetrics": highway_types_data,
                }
            })

        response_body = {
            "routes": route_details_body,
            "waypoints": [
                {
                    "location": [
                        origin['longitude'],
                        origin['latitude']
                    ]
                },
                {
                    "location": [
                        destination['longitude'],
                        destination['latitude']
                    ]
                }
            ]
        }

        return func.HttpResponse(json.dumps(response_body),
                                 status_code=200,
                                 mimetype="application/json"
                                 )

    except ValueError as e:
        logging.error(f'Invalid request: {e}')
        return func.HttpResponse(body='Invalid request', status_code=400)

    except Exception as ex:
        logging.error(f'Exception: {ex}')
        return func.HttpResponse(body='Internal server error', status_code=500)
