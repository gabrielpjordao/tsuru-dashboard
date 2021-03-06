from django.conf import settings

import requests
import json


class MetricNotEnabled(Exception):
    pass


def get_backend(app, token):
    if "envs" in app and "ELASTICSEARCH_HOST" in app["envs"]:
        return ElasticSearch(app["envs"]["ELASTICSEARCH_HOST"], ".measure-tsuru-*", app["name"])

    headers = {'authorization': token}
    url = "{}/apps/{}/metric/envs".format(settings.TSURU_HOST, app["name"])
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        if "METRICS_ELASTICSEARCH_HOST" in data:
            return ElasticSearch(data["METRICS_ELASTICSEARCH_HOST"], ".measure-tsuru-*", app["name"])
    raise MetricNotEnabled


class ElasticSearch(object):
    def __init__(self, url, index, app):
        self.index = index
        self.app = app
        self.url = url

    def post(self, data, metric):
        url = "{}/.measure-tsuru-*/{}/_search".format(self.url, metric)
        data = requests.post(url, data=json.dumps(data))
        return data.json()

    def process(self, data, formatter=None):

        if not formatter:
            def default_formatter(x):
                return x
            formatter = default_formatter

        d = []
        min_value = None
        max_value = 0

        for bucket in data["aggregations"]["range"]["buckets"][0]["date"]["buckets"]:
            bucket_max = formatter(bucket["max"]["value"])
            bucket_min = formatter(bucket["min"]["value"])
            bucket_avg = formatter(bucket["avg"]["value"])

            if min_value is None:
                min_value = bucket_min

            if bucket_min < min_value:
                min_value = bucket_min

            if bucket_max > max_value:
                max_value = bucket_max

            d.append({
                "x": bucket["key"],
                "max": "{0:.2f}".format(bucket_max),
                "min": "{0:.2f}".format(bucket_min),
                "avg": "{0:.2f}".format(bucket_avg),
            })
        return {
            "data": d,
            "min": "{0:.2f}".format(min_value or 0),
            "max": "{0:.2f}".format(max_value),
        }

    def cpu_max(self, date_range=None, interval=None):
        query = self.query(date_range=date_range, interval=interval)
        response = self.post(query, "cpu_max")
        process = self.process(response)
        return process

    def mem_max(self, date_range=None, interval=None):
        query = self.query(date_range=date_range, interval=interval)
        return self.process(self.post(query, "mem_max"), formatter=lambda x: x / (1024 * 1024))

    def units(self, date_range=None, interval=None):
        aggregation = {"units": {"cardinality": {"field": "host"}}}
        query = self.query(date_range=date_range, interval=interval, aggregation=aggregation)
        return self.units_process(self.post(query, "cpu_max"))

    def units_process(self, data, formatter=None):
        d = []
        min_value = None
        max_value = 0

        for bucket in data["aggregations"]["range"]["buckets"][0]["date"]["buckets"]:
            value = bucket["units"]["value"]

            if min_value is None:
                min_value = value

            if value < min_value:
                min_value = value

            if value > max_value:
                max_value = value

            d.append({
                "x": bucket["key"],
                "units": "{0:.2f}".format(value),
            })

        return {
            "data": d,
            "min": "{0:.2f}".format(min_value or 0),
            "max": "{0:.2f}".format(max_value),
        }

    def requests_min(self, date_range=None, interval=None):
        aggregation = {"sum": {"sum": {"field": "count"}}}
        query = self.query(date_range=date_range, interval=interval, aggregation=aggregation)
        return self.requests_min_process(self.post(query, "response_time"))

    def requests_min_process(self, data, formatter=None):
        d = []
        min_value = None
        max_value = 0

        for bucket in data["aggregations"]["range"]["buckets"][0]["date"]["buckets"]:
            value = bucket["sum"]["value"]

            if min_value is None:
                min_value = value

            if value < min_value:
                min_value = value

            if value > max_value:
                max_value = value

            d.append({
                "x": bucket["key"],
                "sum": value,
            })

        return {
            "data": d,
            "min": min_value,
            "max": max_value,
        }

    def response_time(self, date_range=None, interval=None):
        query = self.query(date_range=date_range, interval=interval)
        return self.process(self.post(query, "response_time"))

    def connections_legacy(self, date_range, interval):
        aggregation = {"connection": {"terms": {"field": "connection.raw"}}}
        query = self.query(date_range=date_range, interval=interval, aggregation=aggregation)
        return self.connections_process(self.post(query, "connection"))

    def connections(self, date_range=None, interval=None):
        legacy_data = self.connections_legacy(date_range, interval)
        aggregation = {"connection": {"terms": {"field": "value.raw"}}}
        query = self.query(date_range=date_range, interval=interval, aggregation=aggregation)
        data = self.connections_process(self.post(query, "connection"))
        data["data"].extend(legacy_data["data"])

        if data["min"] is None:
            data["min"] = legacy_data["min"]
        elif legacy_data["min"] is not None and legacy_data["min"] < data["min"]:
            data["min"] = legacy_data["min"]

        if data["max"] is None:
            data["max"] = legacy_data["max"]
        elif legacy_data["max"] is not None and legacy_data["max"] > data["max"]:
            data["max"] = legacy_data["max"]

        return data

    def connections_process(self, data, formatter=None):
        d = []
        min_value = None
        max_value = 0

        for bucket in data["aggregations"]["range"]["buckets"][0]["date"]["buckets"]:
            obj = {}
            obj["x"] = bucket["key"]

            for doc in bucket["connection"]["buckets"]:
                size = doc["doc_count"]
                conn = doc["key"]

                if min_value is None or size < min_value:
                    min_value = size

                if size > max_value:
                    max_value = size

                obj[conn] = size

            d.append(obj)

        return {
            "data": d,
            "min": min_value,
            "max": max_value,
        }

    def query(self, date_range=None, interval=None, aggregation=None):
        if not date_range:
            date_range = "1h/h"

        if not interval:
            interval = "1m"

        query_filter = {
            "filtered": {
                "filter": {
                    "term": {
                        "app.raw": self.app,
                    }
                }
            }
        }
        if not aggregation:
            aggregation = {
                "max": {"max": {"field": "value"}},
                "min": {"min": {"field": "value"}},
                "avg": {"avg": {"field": "value"}}
            }
        return {
            "query": query_filter,
            "size": 0,
            "aggs": {
                "range": {
                    "date_range": {
                        "field": "@timestamp",
                        "ranges": [{
                            "from": "now-" + date_range,
                            "to": "now"
                        }]
                    },
                    "aggs": {
                        "date": {
                            "date_histogram": {
                                "field": "@timestamp",
                                "interval": interval
                            },
                            "aggs": aggregation,
                        }
                    }
                }
            }
        }
