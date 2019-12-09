'''
Created on 15 Apr 2019

Get number of JAMA creator events over last year
Takes a while to run, but displays each day as it goes.

@author: amaccormack
'''

from jamarest import jama

if __name__ == '__main__':
    username = "autocreator"
    import keyring
    password = keyring.get_password("jama", username)
    if not password:
        raise Exception(
            f"Could not retrieve password for JAMA, try: keyring.set_password('jama','{username}','yourpassword')"
        )
    api_base_url = "https://jama.optos.eye/rest/latest"
    
    print(f"Attempting to authenticate to Jama Rest API using base_url {api_base_url}")
    print(f"Attempting to authenticate to Jama Rest API using username is: {username} \n")
    
    jam = jama(base_url=api_base_url, username=username, password=password)
    presp=jam.ask_big('/projects')
    projects={x['id']: x['fields']['name'] for x in presp}

    from datetime import date 
    from datetime import timedelta
    startdate=date.today() - timedelta(days=365)
    enddate=date.today() - timedelta(days=1)
    usermap=jam.get_all_users(include_inactive=True)
    totals={}

    checkdate=startdate
    while checkdate<=enddate:
        userstoday={}
        isodate=checkdate.isoformat()
        for projid, projname in projects.items():
            activities=jam.ask_big('/activities', doseq=True, args={
                'project': projid,
                'date': [f'{isodate}T00:00:00Z', f'{isodate}T23:59:29Z'],
                'eventType': ['UPDATE', 'DELETE', 'CREATE'],
                })
            for act in activities:
                userstoday[act["user"]]=True
        count=len(list(userstoday.keys()))
        print("{}: {} users changed stuff: {}".format(isodate, count, [usermap.get(x, x) for x in userstoday.keys()]))
        totals[isodate]=count
        checkdate=checkdate+timedelta(days=1)
    
    most=max(totals.values())
    print("Most users in a day: {} on {}".format(most, [x for x, y in totals.items() if y==most]))