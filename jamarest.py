"""
JAMA REST API python module
Builds on the code at https://github.com/JamaSoftware/REST-References/tree/master/Python
which is shared with the same MIT licence: https://github.com/JamaSoftware/REST-References/blob/master/LICENSE

The MIT licence:
Copyright (c) 2016-2019 Optos plc
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Code from stackoverflow is covered by CC-BY-SA:
http://meta.stackexchange.com/questions/271080/the-mit-license-clarity-on-using-code-on-stack-overflow-and-stack-exchange
"""

import urllib.parse
import urllib.error
import requests
import time
import re

# Try one version of BeautifulSoup, then another
try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:
    from BeautifulSoup import BeautifulSoup

# Rate limiting decorator
# code from http://stackoverflow.com/questions/667508/whats-a-good-rate-limiting-algorithm/667706#667706
def rate_limited(max_per_second):
    min_interval = 1.0 / float(max_per_second)

    def decorate(func):
        last_time_called = [0.0]

        def rate_limited_function(*args, **kargs):
            elapsed = time.time() - last_time_called[0]
            left_to_wait = min_interval - elapsed
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            ret = func(*args, **kargs)
            last_time_called[0] = time.time()
            return ret

        return rate_limited_function

    return decorate


class jama:
    def __init__(self, base_url, username, password, debug=False, retry_delay=2):
        self.base_url = re.sub("/$", "", base_url)  # remove trailing /
        self.auth = (username, password)
        self.project_id = None
        self.retry_delay = retry_delay
        self.debug = debug
        self.lookup = self.get_lookup()
        self.users = {}

    @rate_limited(12)  # Avoiding overload on server: must be 1 per second at most for JAMA hosted instances
    def ask(self, resource):
        """
        Make a single request to the JAMA REST API, for the named resource, retrying once if we get the throttled response
        :param resource:
        :return
        """
        if resource[0] != "/":
            resource = "/" + resource  # add leading / if required
        full_url = self.base_url + resource
        if self.debug:
            print(full_url)
        try:
            response = requests.get(full_url, auth=self.auth)
        except requests.exceptions.ConnectionError:
            response = requests.get(full_url, auth=self.auth)
        if response.status_code == 429:
            print("Retrying JAMA access")
            time.sleep(self.retry_delay)
            response = requests.get(full_url, auth=self.auth)
            if response.status_code == 429:
                raise Exception("JAMA overload")
        elif response.status_code >= 300:
            raise Exception(f"JAMA API Non-success code {response.status_code} for {full_url}")
        return response

    def _request(self, resource, json, rtype, rstr):
        if resource[0] != "/":
            resource = "/" + resource  # add leading / if required
        full_url = self.base_url + resource
        if self.debug:
            print(rstr, full_url)
        response = rtype(full_url, auth=self.auth, json=json)
        if response.status_code == 401:
            Exception(f"JAMA API Unauthorised when attempting {rstr} as {self.auth[0]}")
        return response

    def put(self, resource, json):
        return self._request(resource, json, requests.put, "PUT")

    def post(self, resource, json):
        return self._request(resource, json, requests.post, "POST")

    def _delete(self, resource):
        return self._request(resource, json, requests.delete, "DELETE")

    def ask_big(self, resource, args={}, field="data", doseq=False):
        """
        Make requests from resource, with args specified, handling the pagination until we have everything
        :param resource: <str> : Endpoint to query
        :param args: <dict> : Arguments to add to URL
        :param field: <str> : Field to bring into return list, default is data
        :param doseq: <bool> : Expand sequences in args to individual paramters in URL (default False)
        :return: <list> :  List of results, or for field "tc", tuple of testcases and results
        """
        start_at = 0
        max_results = 50 # JAMA doesn't allow larger pages than 50
        data = []
        args["maxResults"] = max_results
        fmt = resource + "?"
        tcmap={}
        while True:
            args["startAt"] = start_at
            resp = self.ask(fmt + urllib.parse.urlencode(args, doseq=doseq)).json()
            try:
                if field == "linked" and field in resp:
                    data = data + [y for x, y in resp[field].get("items", {}).items()]
                if field in ("data", "tc"):
                    if type(resp["data"]) is dict:
                        return resp["data"]
                    data = data + resp["data"]
                if field == "tc" and "linked" in resp:
                    tcmap.update({jtcid: tc["documentKey"]  for jtcid, tc in resp["linked"].get("items",{}).items()})
            except KeyError as e:
                raise Exception(
                    f"Fatal error retrieving data from Jama. This usually means the authentication has failed. KeyError for dictionary: {e}"
                )
            start_at = start_at + max_results
            if start_at >= resp["meta"]["pageInfo"]["totalResults"]:
                break
        if field=="tc":
            return(tcmap, data)
        else:
            return data

    def ask_id(self, resource, name, field="name", args={}):
        """
        Get this ID for name from the specified resource, matching the field, with optional args for that resource
        Useful for when we can't search JAMA API directly for these items
        :param resource:
        :param name:
        :param field:
        :param args:
        :return: <int> : JAMA ID of matching item
        """
        resp = self.ask_big(resource, args)
        try:
            if resp:
                return next((item["id"] for item in resp if item[field] == name))
            else:
                return False
        except StopIteration:
            raise Exception(f"Could not find {resource} with {field} matching {name}")

    def ask_count(self, resource, args={}):
        """
        Get the count of results for the given resource, without actually retrieving them all
        :param resource:
        :param args:
        :return:
        """
        fmt = resource + "?"
        resp = self.ask(fmt + urllib.parse.urlencode(args)).json()
        return resp["meta"]["pageInfo"]["totalResults"]

    def ask_dict(self, resource, field="name", args={}):
        """
        Get a dict of the results of the resource's (name) field, with optional args for that resource
        :param resource: <str>
        :param field: <str> Defaults to "name"
        :param args: <dict>
        :return: <dict>
        """
        resp = self.ask_big(resource, args)
        return {item["id"]: item[field] for item in resp}

    def get_project_id(self, project):
        """
        Get the JAMA ID for a project
        :param project: <str>
        :return: <int> : JAMA Project ID
        """
        return self.ask_id("/projects", project, field="projectKey")

    def set_project(self, project):
        """
        Set the project we are talking about
        :param project: <str>
        :return: <int> : JAMA Project ID
        """
        self.project_id = self.get_project_id(project)
        return self.project_id

    def find_filter_id(self, name, project=None):
        """
        For the current project, get the ID of the named filter
        :param name:
        :param project:
        :return:
        """
        if not project:
            project = self.project_id
        elif type(project) is str:
            project = self.get_project_id(project)
        if project:
            return self.ask_id("/filters", name, args={"project": project})
        else:
            raise Exception("JAMA project not set")

    def get_filter_results(self, filter_id, project=None):
        """
        Give me the items from the name / id of the filter
        :param filter_id: <int/str> JAMA Filter name or ID
        :param project: <int> : JAMA Project ID (defaults to set project)
        :return: <list> : requirements matching filter
        """
        if type(filter_id) is str:
            filter_id = self.find_filter_id(filter_id, project)
        return self.ask_big(f"/filters/{filter_id}/results")

    def get_downstream(self, item, args={}):
        """
        Given an item ID, return its downstream related items
        :param item: <int> : Item JAMA ID
        :return: <list> : item's downstream requirements
        """
        args["include"] = "data.toItem"
        return self.ask_big(
            f"/items/{item}/downstreamrelationships", args, field="linked"
        )

    def get_downstreamrelated(self, item, args={}):
        """
        Given an item ID, return its downstream related items
        :param item: <int> : Item JAMA ID
        :return: <list> : item's downstream requirements
        """
        args["include"] = "data.toItem"
        return self.ask_big(f"/items/{item}/downstreamrelated", args)

    def get_downstream_ids(self, item, args={}):
        """
        Given an item ID, return its downstream related items
        :param item: <int> : Item JAMA ID
        :return: <dict> : item's downstream requirement IDs
        """
        data = self.ask_big(f"/items/{item}/downstreamrelationships", args)
        if not data:
            return {}
        else:
            return {x["id"]: x["toItem"] for x in data}

    def get_upstream_ids(self, item, field="id", args={}):
        """
        Given an item ID, return its upstream related items
        :param item: <int> : Item JAMA ID
        :param field: <str> : Field to return, default is ID (JAMA ID)
        :return: <list> : item's upstream requirements
        """
        data = self.ask_big(f"/items/{item}/upstreamrelated", args)
        if not data:
            return []
        else:
            return [x[field] for x in data]

    def get_synced(self, item, args={}):
        """
        Given an item ID, return its synced items
        :param item: <int> : Item JAMA ID
        :return: <list of str> : item's synced requirements
        """
        args["include"] = "data.toItem"
        data = self.ask_big(f"/items/{item}/synceditems", args)
        if not data:
            return []
        else:
            return [x["fields"]["documentKey"] for x in data]

    def get_tags(self, item, args={}):
        """
        Given an item ID, return its tags
        :param item: <int> : Item JAMA ID
        :return: <list of dicts> : item's tags
        """
        data = self.ask_big(f"/items/{item}/tags", args)
        return data

    def get_lookup(self, picklists=["Status"], project=None):
        """
        For the current project, get a big dict of all the custom values mapping to the appropriate strings, given the picklists chosen
        :param picklists:
        :param project:
        :return:
        """
        lookup = {}
        if not project:
            project = self.project_id
        if project:
            lookup.update(self.ask_dict("/releases", args={"project": project}))
        for plist in picklists:
            plid = self.ask_id("/picklists", plist)
            lookup.update(self.ask_dict(f"/picklists/{plid}/options"))
        itemtypes = self.ask_dict("/itemtypes", field="display")
        lookup.update(itemtypes)
        lookup.update({v: k for k, v in itemtypes.items()})
        return lookup

    def find_req_id(self, req_id):
        """
        For a JAMA requirement text ID, return matches
        :param req_id: <str>
        :return: <list>
        """
        return self.ask_big("/abstractitems", {"documentKey": req_id})

    def find_item_id(self, item_id):
        """
        For a JAMA text ID, return matches
        :param item_id: <str>
        :return: <list>
        """
        return self.find_req_id(item_id)

    def find_tc(self, tcname, project=None):
        """
        Find a test case name
        :param tcname: <str> :  Test case name to find
        :param project: <int> : Project to search, default is current set project
        :return: <list>
        """
        if not project:
            project = self.project_id
        return self.ask_big(
            "/abstractitems",
            {
                "itemType": self.lookup["Test Case"],
                "project": project,
                "contains": [tcname],
            },
        )

    def find_by_name(self, name, itemtype=None, project=None):
        """
        Find a matching item
        :param name: <str> :  Test case name to find
        :param itemtype: <str/int> :  Item type to find
        :param project: <int> : Project to search, default is current set project
        :return: <list>
        """
        if not project:
            project = self.project_id
        criteria = {"contains": [name], "project": project}
        if itemtype:
            if type(itemtype) is str:
                if itemtype in self.lookup:
                    criteria["itemType"] = self.lookup[itemtype]
            else:
                criteria["itemType"] = itemtype
        return self.ask_big("/abstractitems", criteria)

    def find_uniqid(self, uniqid):
        """
        Given JAMA API int id, return the JAMA string ID
        :param uniqid: <int> : Item to find
        :return: <str> : JAMA string ID
        """
        resp = self.ask(f"/abstractitems/{uniqid}").json()
        return resp["data"]["documentKey"]

    def testrun_islocked(self, test_id):
        """
        Check if test run is locked
        :param test_id: <int> : Test run ID
        :return: <bool> : Lock status
        """
        resp = self.ask(f"/testruns/{test_id}/lock").json()
        return resp["data"]["locked"]

    def setlock_testrun(self, test_id, locked):
        """
        Set test run lock status
        :param test_id: <int> : Test run ID
        :param locked: <bool> : Lock status
        """
        resp = self.put(f"/testruns/{test_id}/lock", {"locked": locked})
        return resp

    def lock_testrun(self, test_id):
        """
        Lock test run
        :param test_id: <int> : Test run ID
        """
        self.setlock_testrun(test_id, True)

    def unlock_testrun(self, test_id):
        """
        Unlock test run
        :param test_id: <int> : Test run ID
        """
        self.setlock_testrun(test_id, False)

    def create_testcase(self, parent_id, name, description, steps, project=None):
        """
        Create a new test case
        :param parent_id: <int/string> : The parent JAMA item to create test case within
        :param name: <string> : The name of the test case
        :param description: <string> : The description of the test case
        :param steps: <list of dicts> : The test steps. Each step must have fields action, expectedResult and notes in a dict.
        :param project: <int/string> : The project to create test case in, defaults to set project
        :return: <int> : id of created test_case
        """
        # Handle non-id arguments
        if not project:
            project = self.project_id
        if type(project) is str:
            project = self.get_project_id(project)
        if type(parent_id) is str:
            parent_id = self.find_item_id(parent_id)

        tc_item = self.lookup["Test Case"]
        fields = {"description": description, "name": name, "testCaseSteps": steps}
        json = {
            "project": project,
            "itemType": tc_item,
            "childItemType": tc_item,
            "location": {"parent": parent_id},
            "fields": fields,
        }

        resp = self.post("/items", json)
        try:
            test_case = resp.json()["meta"]["id"]
        except KeyError:
            print("NO ID RETURNED:", resp.json())
        return test_case

    def search(self, contains, item_type=None):
        """
        Find items that match a string
        :param contains: <string> : String to search for within items
        :param item_type: <int/string> : The type of item to search for (default: all)
        :return: <list of dicts> : search results
        """
        if type(item_type) is str:
            item_type = self.lookup[item_type]
        criteria = {"contains": contains}
        if item_type:
            criteria["itemType"] = item_type
        return self.ask_big("/abstractitems", criteria)

    def create_testplan(self, name, project=None):
        """
        Create a new test plan
        :param name: <string> : The name of the test plan
        :param project: <int/string> : The project to create test plan in, defaults to set project
        :return: <int> : id of created test_plan
        """
        # Handle non-id arguments
        if not project:
            project = self.project_id
        if type(project) is str:
            project = self.get_project_id(project)

        fields = {"name": name}
        json = {"project": project, "fields": fields}

        resp = self.post("/testplans", json)
        test_plan = resp.json()["meta"]["id"]
        return test_plan

    # Create groups
    def create_testgroup(self, plan, name):
        """
        Create a test group within a plan, return its test group ID
        :param plan <int> : Plan JAMA ID
        :param name <str> : Group name to create
        :return: <int> : Test groups in plan
        """
        json = {"name": name}
        resp = self.post(f"/testplans/{plan}/testgroups", json)
        try:
            test_group = resp.json()["meta"]["id"]
        except KeyError:
            print(resp.reason)
            print(resp.text)
            raise Exception("Creating testgroup failed")
        return test_group

    def get_plangroups(self, plan):
        """
        Given an test plan, return its test groups
        :param plan <int> : Plan JAMA ID
        :return: <list of dicts> : Test groups in plan
        """
        return self.ask_big(f"/testplans/{plan}/testgroups")

    def get_groupcases(self, plan, group):
        """
        Given an test plan and group ID, return its test cases
        :param plan <int> : Plan JAMA ID
        :param group <int> : Group JAMA ID
        :return: <list of dicts> : Test cases in group
        """
        return self.ask_big(f"/testplans/{plan}/testgroups/{group}/testcases")

    def get_plancycles(self, plan):
        """
        Given an plan ID, return its test cycles
        :param plan <int> : Plan JAMA ID
        :return: <list of dicts> : Test cycles in plan
        """
        return self.ask_big(f"/testplans/{plan}/testcycles")

    def get_links(self, item_id):
        """
        Given an item ID, return its links
        :param item_id: <int> : Item JAMA ID
        :return: <list of dicts> : item's links
        """
        return self.ask_big(f"/items/{item_id}/links")

    def add_tests_to_plan(self, plan, tests, group=None):
        """
        add test cases to plan
        :param plan: <int> : The parent JAMA item to add test case to
        :param tests: <list of ints> : The test cases to add.
        :param group: <int> : The group to create test case in, defaults to default group
        :return: <int> : Returns the test group added to
        """
        if not group:
            groups = self.get_plangroups(plan)
            group = groups[0]["id"]
        for test in tests:
            json = {"testCase": test}
            response = self.post(
                f"/testplans/{plan}/testgroups/{group}/testcases", json
            )
        return group

    def create_testcycle(
        self,
        name,
        plan,
        groups=None,
        description=None,
        startdate=None,
        enddate=None,
        statuses=None,
        cyclerefresh=None,
    ):
        """
        create test_cycle
        :param name: <string> : The name of the test cycle
        :param plan: <int> : Test plan for cycle
        :param groups: <list of ints> : The test groups to include in cycle, default all
        :param description:
        :param startdate: <YYYY-MM-DD string> : The start date for the cycle, defaults to today
        :param enddate: <YYYY-MM-DD string> : The end date for the cycle, defaults to start date
        :param statuses: <list of strings> : The test cases' statuses to include (default all)
        :param cyclerefresh: int :  If we are just refreshing existing cycle, the cycle ID, if None (default) then create new one
        :return: <int> : The new test_cycle id
        """
        if not startdate:
            from datetime import date

            startdate = date.today().isoformat()
        if not enddate:
            enddate = startdate

        cycle_payload = {
            "fields": {
                "name": name,
                "description": description,
                "startDate": startdate,
                "endDate": enddate,
            },
            "testRunGenerationConfig": {},
        }
        if groups:
            cycle_payload["testRunGenerationConfig"]["testGroupsToInclude"] = groups
        if statuses:
            cycle_payload["testRunGenerationConfig"][
                "testRunStatusesToInclude"
            ] = statuses
        if cyclerefresh:
            response = self.put(f"/testcycles/{cyclerefresh}", cycle_payload)
            return
        else:
            response = self.post(f"/testplans/{plan}/testcycles", cycle_payload)
        try:
            test_cycle = response.json()["meta"]["id"]
        except KeyError:
            print(response.json()["meta"]["message"])
            raise KeyError
        return test_cycle

    def find_user(self, first_name, last_name):
        """
        Given a name, look up the user ID
        :param first_name: <str> : First name of user
        :param first_name: <last_name> : Last name of user
        :return: <int> : The JAMA User ID
        """
        key = (first_name, last_name)
        if key in self.users:
            return self.users[key]
        else:
            data = self.ask_big(
                "/users", args={"firstName": first_name, "lastName": last_name}
            )
            user_id = data[0]["id"]
            self.users[key] = user_id
            return user_id

    def checkout_runsteps(self, testrun):
        """
        checked out a run's steps so we can update them
        :param testrun: <int> : The id of the test run
        :return: <list of dicts> : The steps to be executed
        """
        self.lock_testrun(testrun)
        run = self.ask_big(f"/testruns/{testrun}")
        f = run["fields"]
        if self.debug:
            print(f"Retrieved testrun {testrun} with {len(f['testRunSteps'])} steps")
        return f["testRunSteps"]

    def checkin_runsteps(self, testrun, steps, tester=None, resulttext=None):
        """
        after they have been checked out, update the test steps for a run and unlock
        :param testrun: <int> : The id of the test run
        :param steps: <list of dicts> : Array (for each step) of dicts, each step having fields "result" and "status"
        :param tester: <int/str> : id or name of tester assigned to the run
        :param resulttext: <string> : Rich text of any other info for test run
        """
        data = self.ask_big(f"/testruns/{testrun}")
        fields = data["fields"]
        try:
            del fields["testRunStatus"]
            del fields["executionDate"]
        except KeyError:
            pass
        fields["testRunSteps"] = steps
        if tester:
            if type(tester) is str:
                names = tester.split(" ")
                tester = self.find_user(names[0], " ".join(names[1:]))
            fields["assignedTo"] = tester
        if resulttext:
            fields["actualResults"] = resulttext
        resp = self.put(f"/testruns/{testrun}", {"fields": fields}).json()
        self.unlock_testrun(testrun)
        if resp["meta"]["status"] == "Bad Request":
            raise Exception(
                f"checkin_runsteps on run {testrun} ERROR: {resp['meta']['message']}, ({len(steps)} steps)"
            )
        return resp

    def get_testruns(self, cycle):
        """
        Get all testruns for a test cycle
        :param cycle: <int> : The id of the test run
        :return: <list> : List of test runs
        """
        data = self.ask_big(f"/testcycles/{cycle}/testruns")
        return data

    def get_testrunsx(self, cycle):
        """
        Get all testruns for a test cycle, with the test case info
        :param cycle: <int> : The id of the test run
        :return: <list> : List of test runs with test case info
        """
        data = self.ask_big(
            f"/testcycles/{cycle}/testruns",
            field="tc",
            args={"include": "data.fields.testCase"},
        )
        return data

    def get_testgroups(self, plan):
        """
        Get all testgroups for a test plan
        :param plan: <int> : The id of the test plan
        :return: <dict> : Dict of test groups name:id
        """
        data = self.ask_big(f"/testplans/{plan}/testgroups")
        return {x["name"]: x["id"] for x in data}

    def get_testcycles(self, plan):
        """
        Get all testcycles for a test plan
        :param plan: <int> : The id of the test plan
        :return: <dict> : Dict of test cycles name:id
        """
        data = self.ask_big(f"/testplans/{plan}/testcycles")
        return {x["fields"]["name"]: x["id"] for x in data}

    def get_all_users(self, include_inactive=False):
        """
        Get all users in JAMA
        :param include_inactive: <bool> : Include inactive users (defualt false)
        :return: <dict> : Dict of users id:name
        """
        data = self.ask_big("/users", args={"includeInactive" : include_inactive})
        return {x["id"]: f"{x['firstName']} {x['lastName']}" for x in data}

    def get_req_text(self, req_id):
        """
        Get rendered version of requirement text
        :param req_id: <str> : Requirement identifier
        :return: <list> : rendered text lines from requirement
        """
        results = self.find_req_id(req_id)
        if len(results) != 1:
            print(f"Ambiguous/empty match for requirement {req_id}")
            return []
        else:
            contents_string = results[0]["fields"]["description"]
            bs = BeautifulSoup(
                contents_string, convertEntities=BeautifulSoup.HTML_ENTITIES
            )
            txt = bs.getText("\n")
            return [re.sub("[\r\n]*$", "", x) for x in txt.split("\n")]

    def create_link(self, item, url, description):
        """
        Create link from item
        :param item: <int> : JAMA ID of item
        :param url: <str> : URL for link
        :param description: <str> : Text of link
        :return: <requests response>
        """
        json = {"url": url, "description": description}
        resp = self.post(f"/items/{item}/links", json)
        return resp

    def create_relationship(self, upstream, downstream, relationship_type=None):
        """
        Create a relationship between two items
        :param upstream: <int> : JAMA ID of item
        :param downstream: <int> : JAMA ID of item
        :param relationship_type: <int> : JAMA ID of relationship type
        :return: <requests response>
        """
        json = {"fromItem": upstream, "toItem": downstream}
        if relationship_type:
            json["relationshipType"] = relationship_type
        resp = self.post("/relationships", json).json()
        if resp["meta"]["status"] == "Bad Request":
            raise Exception(f"create_relationship ERROR: {resp['meta']['message']}")
        return resp

    def remove_testrun(self, testrun):
        """
        Delete a test run
        :param testrun: <int> : The id of the test run
        :return: <requests response>
        """
        return self._delete(f"/testruns/{testrun}")

