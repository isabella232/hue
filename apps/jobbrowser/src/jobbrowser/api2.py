#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging

from django.http import HttpResponse, FileResponse
from django.utils.translation import ugettext as _

from desktop.lib.rest.http_client import RestException
from desktop.lib.i18n import smart_unicode
from desktop.lib.django_util import JsonResponse
from desktop.lib.rest.http_client import HttpClient
from desktop.lib.rest.resource import Resource
from desktop.views import serve_403_error
from beeswax.conf import USE_SASL

from jobbrowser.apis.base_api import get_api
from jobbrowser.conf import DISABLE_KILLING_JOBS, QUERY_STORE, USE_PROXY

LOG = logging.getLogger(__name__)


def api_error_handler(func):
  def decorator(*args, **kwargs):
    response = {}

    try:
      return func(*args, **kwargs)
    except Exception as e:
      LOG.exception('Error running %s' % func)
      response['status'] = -1
      response['message'] = smart_unicode(e)
    finally:
      if response:
        return JsonResponse(response)

  return decorator


@api_error_handler
def jobs(request, interface=None):
  response = {'status': -1}

  cluster = json.loads(request.POST.get('cluster', '{}'))
  interface = interface or json.loads(request.POST.get('interface'))
  filters = dict([(key, value) for _filter in json.loads(
      request.POST.get('filters', '[]')) for key, value in list(_filter.items()) if value
  ])
  if interface == 'queries-hive':
    filters = json.loads(request.body)

  jobs = get_api(request.user, interface, cluster=cluster).apps(filters)

  response['apps'] = jobs['apps']
  response['total'] = jobs.get('total')
  response['status'] = 0

  if interface == 'queries-hive':
    return JsonResponse(response['apps'])
  else:
    return JsonResponse(response)


@api_error_handler
def job(request, interface=None):
  response = {'status': -1}

  cluster = json.loads(request.POST.get('cluster', '{}'))
  interface = interface or json.loads(request.POST.get('interface'))
  if interface == 'queries-hive':
    app_id = json.loads(request.body)['queryId']
  else:
    app_id = json.loads(request.POST.get('app_id'))

  if interface == 'schedules':
    offset = json.loads(request.POST.get('pagination', '{"offset": 1}')).get('offset')
    response_app = get_api(request.user, interface, cluster=cluster).app(app_id, offset=offset)
  else:
    response_app = get_api(request.user, interface, cluster=cluster).app(app_id)

  if response_app.get('status') == -1 and response_app.get('message'):
    response.update(response_app)
  else:
    response['app'] = response_app
    response['status'] = 0

  if interface == 'queries-hive':
    return JsonResponse(response['app'])
  else:
    return JsonResponse(response)


@api_error_handler
def action(request, interface=None, action=None):
  response = {'status': -1, 'message': ''}

  cluster = json.loads(request.POST.get('cluster', '{}'))
  interface = json.loads(request.POST.get('interface'))
  app_ids = json.loads(request.POST.get('app_ids'))
  operation = json.loads(request.POST.get('operation'))

  if operation.get('action') == 'kill' and DISABLE_KILLING_JOBS.get():
    return serve_403_error(request)

  response['operation'] = operation
  response.update(
      get_api(request.user, interface, cluster=cluster).action(app_ids, operation, request)
  )

  return JsonResponse(response)


@api_error_handler
def logs(request):
  response = {'status': -1}

  cluster = json.loads(request.POST.get('cluster', '{}'))
  interface = json.loads(request.POST.get('interface'))
  app_id = json.loads(request.POST.get('app_id'))
  app_type = json.loads(request.POST.get('type'))
  log_name = json.loads(request.POST.get('name'))

  response['logs'] = get_api(request.user, interface, cluster=cluster).logs(
      app_id, app_type, log_name, json.loads(request.GET.get('is_embeddable', 'false').lower())
  )
  response['status'] = 0

  return JsonResponse(response)


@api_error_handler
def profile(request):
  response = {'status': -1}

  cluster = json.loads(request.POST.get('cluster', '{}'))
  interface = json.loads(request.POST.get('interface'))
  app_id = json.loads(request.POST.get('app_id'))
  app_type = json.loads(request.POST.get('app_type'))
  app_property = json.loads(request.POST.get('app_property'))
  app_filters = dict([
      (key, value) for _filter in json.loads(request.POST.get('app_filters', '[]'))
      for key, value in list(_filter.items()) if value
  ])

  api = get_api(request.user, interface, cluster=cluster)
  api._set_request(request) # For YARN

  resp = api.profile(app_id, app_type, app_property, app_filters)

  if isinstance(resp, HttpResponse):
    return resp
  else:
    response[app_property] = resp
    response['status'] = 0
    return JsonResponse(response)


@api_error_handler
def query_store_api(request, path=None):
  response = {'status': -1}

  if USE_PROXY.get():
    content_type = 'application/json; charset=UTF-8'
    headers = {'X-Requested-By': 'das', 'Content-Type': content_type}

    client = HttpClient(QUERY_STORE.SERVER_URL.get())
    resource = Resource(client)
    if USE_SASL.get():
      client.set_kerberos_auth()

    try:
      response = resource.invoke(request.method, path, request.GET.dict(), request.body, headers)
    except RestException as e:
      ex_response = e.get_parent_ex().response
      response['code'] = ex_response.status_code
      response['message'] = ex_response.reason
      response['content'] = ex_response.text
  else:
    if path == 'api/query/search':
      filters = json.loads(request.body)
      resp = get_api(request.user, interface='queries-hive').apps(filters['search'])
      response = resp['apps']

  return JsonResponse(response)


@api_error_handler
def query_store_download_bundle(request, id=None):
  response = {}

  client = HttpClient(QUERY_STORE.SERVER_URL.get())
  resource = Resource(client)
  if USE_SASL.get():
    client.set_kerberos_auth()

  app = resource.get('api/data-bundle/' + id)

  response = FileResponse((app, 'rb'), content_type='application/octet-stream')
  response['Content-Disposition'] = 'attachment; filename=' + id + '.zip'

  return response
