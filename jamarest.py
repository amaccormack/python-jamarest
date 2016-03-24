# JAMA REST API python module
# Builds on the code at https://github.com/JamaSoftware/REST-References/tree/master/Python
# which is shared with the same MIT licence: https://github.com/JamaSoftware/REST-References/blob/master/LICENSE
#
# The MIT licence:
# Copyright (c) 2016 Optos plc
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

# Code from stackoverflow is covered by CC-BY-SA:
# http://meta.stackexchange.com/questions/271080/the-mit-license-clarity-on-using-code-on-stack-overflow-and-stack-exchange
# Code from github covered by 


import requests
import urllib
import time

# Rate limiting decorator
# code from http://stackoverflow.com/questions/667508/whats-a-good-rate-limiting-algorithm/667706#667706
def RateLimited(maxPerSecond):
    minInterval = 1.0 / float(maxPerSecond)
    def decorate(func):
        lastTimeCalled = [0.0]
        def rateLimitedFunction(*args,**kargs):
            elapsed = time.time() - lastTimeCalled[0]
            leftToWait = minInterval - elapsed
            if leftToWait>0:
                time.sleep(leftToWait)
            ret = func(*args,**kargs)
            lastTimeCalled[0] = time.time()
            return ret
        return rateLimitedFunction
    return decorate



class jama:
    def __init__(self, base_url, username, password):
        self.base_url=base_url
        self.auth=(username, password)
        self.project_id=None
        self.retry_delay=2

    @RateLimited(1)  # 1 per second at most
    def ask(self, resource):
        "Make a single request to the JAMA REST API, for the named resource, retrying once if we get the throttled response"
        response = requests.get(self.base_url + resource, auth=self.auth) 
        if response.status_code == 429:
            print "retry"
            time.sleep(self.retry_delay)
            response = requests.get(self.base_url + resource, auth=self.auth)
            if response.status_code == 429:
                raise Exception('JAMA overload')
        if response.status_code >= 300:
            print "JAMA API Non-success code {0} for {1}".format(response.status_code, resource)
        return response
    
    def ask_big(self, resource, args={}):
        "Make requests from resource, with args specified, handling the pagination until we have everything"
        startAt=0
        maxResults=50
        data=[]
        args.update({'startAt': startAt, 'maxResults': maxResults})
        fmt=resource+"?"
        while True:
            args['startAt']=startAt
            resp=self.ask(fmt+urllib.urlencode(args)).json()
            data=data+resp['data']
            startAt=startAt+maxResults
            if startAt >= resp['meta']['pageInfo']['totalResults']:
                break
        return data   
    
    def ask_id(self, resource, name, field='name', args={}):
        "Get ths ID for name from the specified resource, matching the field, with optional args for that resource"
        resp=self.ask_big(resource, args)
        return (item['id'] for item in resp if item[field] == name).next()
    
    def ask_dict(self, resource, field='name', args={}):
        "Get a dict of the results of the resource's (name) field, with optional args for that resource"
        resp=self.ask_big(resource, args)
        return {item['id']: item[field] for item in resp}

    def set_project(self, project):
        "Set the project we are talking about"
        self.project_id=self.ask_id('/projects', project, field='projectKey')
        return self.project_id
    
    def find_filter_id(self, name):
        "For the current project, get the ID of the named filter"
        if self.project_id:
            return self.ask_id('/filters', name, args={'project': self.project_id})
        else:
            raise Exception('JAMA project not set')

    def get_filter_results(self, filter_id):
        "Give me the items from the name / id of the filter"
        if type(filter_id) is str:
            filter_id=self.find_filter_id(filter_id)
        return self.ask_big('/filters/{0}/results'.format(filter_id))
        
    def get_lookup(self, picklists=['Status']):
        "For the current project, get a big dict of all the custom values mapping to the appropriate strings, given the picklists chosen"
        if self.project_id:
            lookup={}
            lookup.update(self.ask_dict('/releases', args={'project': self.project_id}))
            lookup.update(self.ask_dict('/itemtypes', field='display'))
            for plist in picklists:
                plid=self.ask_id('/picklists', plist)
                lookup.update(self.ask_dict('/picklists/{0}/options'.format(plid)))
            return lookup
        else:
            raise Exception('JAMA project not set')

    
