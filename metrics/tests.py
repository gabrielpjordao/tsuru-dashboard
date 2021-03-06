from django.test import TestCase
from django.test.client import RequestFactory
from django.conf import settings

from metrics.backend import ElasticSearch, get_backend, MetricNotEnabled
from metrics import views

import mock
import json


class MetricViewTest(TestCase):
    def request(self):
        request = RequestFactory().get("/ble/?metric=cpu_max")
        request.session = {"tsuru_token": "token"}
        return request

    @mock.patch("requests.get")
    def test_get_app(self, get_mock):
        response_mock = mock.Mock()
        response_mock.json.return_value = {}
        get_mock.return_value = response_mock

        view = views.Metric()
        view.request = self.request()
        app = view.get_app("app_name")

        self.assertDictEqual(app, {})
        url = "{}/apps/app_name".format(settings.TSURU_HOST)
        headers = {"authorization": "token"}
        get_mock.assert_called_with(url, headers=headers)

    @mock.patch("requests.get")
    def test_get_envs(self, get_mock):
        env_mock = [{"name": "VAR", "value": "value"}]
        response_mock = mock.Mock()
        response_mock.json.return_value = env_mock
        get_mock.return_value = response_mock

        view = views.Metric()
        view.request = self.request()
        envs = view.get_envs(self.request(), "app_name")

        self.assertDictEqual(envs, {"VAR": "value"})
        url = "{}/apps/app_name/env".format(settings.TSURU_HOST)
        headers = {"authorization": "token"}
        get_mock.assert_called_with(url, headers=headers)

    @mock.patch("metrics.backend.get_backend")
    @mock.patch("auth.views.token_is_valid")
    def test_get(self, token_mock, get_backend_mock):
        token_mock.return_value = True
        backend_mock = mock.Mock()
        backend_mock.cpu_max.return_value = {}
        get_backend_mock.return_value = backend_mock

        v = views.Metric

        original_get_app = v.get_app
        v.get_app = mock.Mock()
        v.get_app.return_value = {}

        original_get_envs = v.get_envs
        v.get_envs = mock.Mock()
        v.get_envs.return_value = {}
        view = v.as_view()

        def cleanup():
            v.get_app = original_get_app
            v.get_envs = original_get_envs

        self.addCleanup(cleanup)

        request = RequestFactory().get("/ble/?metric=cpu_max&date_range=2h/h&interval=30m")
        request.session = {"tsuru_token": "token"}

        response = view(request, app_name="app_name")

        self.assertEqual(response.status_code, 200)
        get_backend_mock.assert_called_with({'envs': {}}, 'token')
        backend_mock.cpu_max.assert_called_with(date_range=u'2h/h', interval=u'30m')

    @mock.patch("auth.views.token_is_valid")
    def test_get_bad_request(self, token_mock):
        request = RequestFactory().get("")
        request.session = {"tsuru_token": "token"}
        token_mock.return_value = True

        v = views.Metric
        view = v.as_view()

        response = view(request, app_name="app_name")

        self.assertEqual(response.status_code, 400)


class BackendTest(TestCase):
    @mock.patch("requests.get")
    def test_envs_from_api(self, get_mock):
        response_mock = mock.Mock(status_code=200)
        response_mock.json.return_value = {
            "METRICS_BACKEND": "logstash",
            "METRICS_ELASTICSEARCH_HOST": "http://easearch.com",
            "METRICS_LOGSTASH_HOST": "logstash.com"
        }
        get_mock.return_value = response_mock

        app = {"name": "appname"}

        backend = get_backend(app, 'token')
        self.assertIsInstance(backend, ElasticSearch)

    def test_envs_from_app(self):
        app = {"name": "appname", "envs": {"ELASTICSEARCH_HOST": "ble"}}

        backend = get_backend(app, 'token')
        self.assertIsInstance(backend, ElasticSearch)

    @mock.patch("requests.get")
    def test_without_metrics(self, get_mock):
        get_mock.return_value = mock.Mock(status_code=404)
        app = {"name": "appname"}

        with self.assertRaises(MetricNotEnabled):
            get_backend(app, 'token')


class ElasticSearchTest(TestCase):
    def setUp(self):
        self.maxDiff = None
        self.es = ElasticSearch("http://url.com", "index", "app")

    @mock.patch("requests.post")
    def test_cpu_max(self, post_mock):
        self.es.process = mock.Mock()
        self.es.cpu_max()
        url = "{}/.measure-tsuru-*/{}/_search".format(self.es.url, "cpu_max")
        post_mock.assert_called_with(url, data=json.dumps(self.es.query()))

    @mock.patch("requests.post")
    def test_mem_max(self, post_mock):
        self.es.process = mock.Mock()
        self.es.mem_max()
        url = "{}/.measure-tsuru-*/{}/_search".format(self.es.url, "mem_max")
        post_mock.assert_called_with(url, data=json.dumps(self.es.query()))

    @mock.patch("requests.post")
    def test_units(self, post_mock):
        self.es.units()
        url = "{}/.measure-tsuru-*/{}/_search".format(self.es.url, "cpu_max")
        aggregation = {"units": {"cardinality": {"field": "host"}}}
        post_mock.assert_called_with(url, data=json.dumps(self.es.query(aggregation=aggregation)))

    @mock.patch("requests.post")
    def test_requests_min(self, post_mock):
        self.es.requests_min()
        url = "{}/.measure-tsuru-*/{}/_search".format(self.es.url, "response_time")
        aggregation = {"sum": {"sum": {"field": "count"}}}
        post_mock.assert_called_with(url, data=json.dumps(self.es.query(aggregation=aggregation)))

    @mock.patch("requests.post")
    def test_response_time(self, post_mock):
        self.es.response_time()
        url = "{}/.measure-tsuru-*/{}/_search".format(self.es.url, "response_time")
        post_mock.assert_called_with(url, data=json.dumps(self.es.query()))

    @mock.patch("requests.post")
    def test_connections(self, post_mock):
        data = {
            "took": 132,
            "timed_out": False,
            "_shards": {
                "total": 380,
                "successful": 380,
                "failed": 0
            },
            "hits": {
                "total": 478998,
                "max_score": 0,
                "hits": []
            },
            "aggregations": {
                "range": {
                    "buckets": [
                        {
                            "key": "2015-09-16T21:42:00.000Z-2015-09-16T21:47:05.700Z",
                            "from": 1442439720000,
                            "from_as_string": "2015-09-16T21:42:00.000Z",
                            "to": 1442440025700,
                            "to_as_string": "2015-09-16T21:47:05.700Z",
                            "doc_count": 1,
                            "date": {
                                "buckets": [
                                    {
                                        "key_as_string": "2015-09-16T21:40:00.000Z",
                                        "key": 1442439600000,
                                        "doc_count": 1,
                                        "connection": {
                                            "doc_count_error_upper_bound": 0,
                                            "sum_other_doc_count": 0,
                                            "buckets": [
                                                {
                                                    "key": "tsuru.company.com:80",
                                                    "doc_count": 50
                                                },
                                                {
                                                    "key": "remote.something.com:8080",
                                                    "doc_count": 13
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        }
        response = mock.Mock()
        response.json.return_value = data
        post_mock.return_value = response
        result = self.es.connections()
        expected = {"data": [{
            "x": 1442439600000,
            "tsuru.company.com:80": 50,
            "remote.something.com:8080": 13,
        }, {
            "x": 1442439600000,
            "tsuru.company.com:80": 50,
            "remote.something.com:8080": 13,
        }], "min": 13, "max": 50}
        self.assertEqual(expected, result)
        url = "{}/.measure-tsuru-*/{}/_search".format(self.es.url, "connection")
        legacy_aggregation = {"connection": {"terms": {"field": "connection.raw"}}}
        aggregation = {"connection": {"terms": {"field": "value.raw"}}}
        expected_calls = [
            mock.call(url, data=json.dumps(self.es.query(aggregation=legacy_aggregation))),
            mock.call(url, data=json.dumps(self.es.query(aggregation=aggregation))),
        ]
        self.assertEqual(expected_calls, post_mock.call_args_list)

    def test_process(self):
        data = {
            "took": 86,
            "timed_out": False,
            "_shards": {
                "total": 266,
                "successful": 266,
                "failed": 0
            },
            "hits": {
                "total": 644073,
                "max_score": 0,
                "hits": []
            },
            "aggregations": {
                "range": {
                    "buckets": [
                        {
                            "key": "2015-07-21T19:35:00.000Z-2015-07-21T19:37:05.388Z",
                            "from": 1437507300000,
                            "from_as_string": "2015-07-21T19:35:00.000Z",
                            "to": 1437507425388,
                            "to_as_string": "2015-07-21T19:37:05.388Z",
                            "doc_count": 18,
                            "date": {
                                "buckets": [
                                    {
                                        "key_as_string": "2015-07-21T19:35:00.000Z",
                                        "key": 1437507300000,
                                        "doc_count": 9,
                                        "min": {
                                            "value": 97517568
                                        },
                                        "max": {
                                            "value": 97517568
                                        },
                                        "avg": {
                                            "value": 97517568
                                        }
                                    },
                                    {
                                        "key_as_string": "2015-07-21T19:36:00.000Z",
                                        "key": 1437507360000,
                                        "doc_count": 9,
                                        "min": {
                                            "value": 97517568
                                        },
                                        "max": {
                                            "value": 97517568
                                        },
                                        "avg": {
                                            "value": 97517568
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        }
        expected = {
            "data": [
                {
                    "x": 1437507300000,
                    "max": '97517568.00',
                    "min": '97517568.00',
                    "avg": '97517568.00'
                },
                {
                    "x": 1437507360000,
                    "max": '97517568.00',
                    "min": '97517568.00',
                    "avg": '97517568.00'
                }
            ],
            "min": '97517568.00',
            "max": '97517568.00'
        }
        d = self.es.process(data)
        self.assertDictEqual(d, expected)

    def test_process_custom_formatter(self):
        data = {
            "took": 86,
            "timed_out": False,
            "_shards": {
                "total": 266,
                "successful": 266,
                "failed": 0
            },
            "hits": {
                "total": 644073,
                "max_score": 0,
                "hits": []
            },
            "aggregations": {
                "range": {
                    "buckets": [
                        {
                            "key": "2015-07-21T19:35:00.000Z-2015-07-21T19:37:05.388Z",
                            "from": 1437507300000,
                            "from_as_string": "2015-07-21T19:35:00.000Z",
                            "to": 1437507425388,
                            "to_as_string": "2015-07-21T19:37:05.388Z",
                            "doc_count": 18,
                            "date": {
                                "buckets": [
                                    {
                                        "key_as_string": "2015-07-21T19:35:00.000Z",
                                        "key": 1437507300000,
                                        "doc_count": 9,
                                        "min": {
                                            "value": 97517568
                                        },
                                        "max": {
                                            "value": 97517568
                                        },
                                        "avg": {
                                            "value": 97517568
                                        }
                                    },
                                    {
                                        "key_as_string": "2015-07-21T19:36:00.000Z",
                                        "key": 1437507360000,
                                        "doc_count": 9,
                                        "min": {
                                            "value": 97517568
                                        },
                                        "max": {
                                            "value": 97517568
                                        },
                                        "avg": {
                                            "value": 97517568
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        }
        expected = {
            "data": [
                {
                    "x": 1437507300000,
                    "max": '93.00',
                    "min": '93.00',
                    "avg": '93.00'
                },
                {
                    "x": 1437507360000,
                    "max": '93.00',
                    "min": '93.00',
                    "avg": '93.00'
                }
            ],
            "min": '93.00',
            "max": '93.00'
        }
        d = self.es.process(data, formatter=lambda x: x / (1024 * 1024))
        self.assertDictEqual(d, expected)
