from mcp.server.fastmcp import FastMCP
import requests
import urllib.parse
import datetime
import os
import zoneinfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Update the instructions for your MCP server
instructions = """
This is the instruction / prompt for your MCP server. Include instructions on when to use this MCP server and what it can do.
""".strip()

# Create an MCP server
mcp = FastMCP("mcp_gcal", instructions=instructions)


def get_gcal_credentials():
    """
    Looks for credentials and generate a valid token
    
    Taken from https://github.com/googleworkspace/python-samples/blob/main/calendar/quickstart/quickstart.py
    
    Returns:
        creds: Google API OAUTH2 Credentials
    """
    creds = None
    GCAL_TOKEN_PATH = None
    GCAL_CREDENTIALS_PATH = None
    SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
    try:
        GCAL_TOKEN_PATH = os.environ['GCAL_TOKEN_PATH']
        GCAL_CREDENTIALS_PATH = os.environ['GCAL_CREDENTIALS_PATH']
        # GCAL_TOKEN_PATH = "/Users/salinas/.config/goose/mcp-gcal/token.json"
        # GCAL_CREDENTIALS_PATH="/Users/salinas/.config/goose/mcp-gcal/credentials.json"
    except KeyError as error:
        raise KeyError(f"Can't find enviroment variable {error}") from error
    except Exception as error:
        raise error
    
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(GCAL_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(GCAL_TOKEN_PATH, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Needs credentials.json to generate the token
            # credentials.json is downloaded from the GCP project
            flow = InstalledAppFlow.from_client_secrets_file(
                GCAL_CREDENTIALS_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open("token.json", "w") as token:
        token.write(creds.to_json())
    
    return (creds)

@mcp.tool()
def get_timezone_difference(tz1: str, tz2: str) -> dict:
    """Calculate the time difference (hours) between two given timezones

    Args:
        tz1 (str): A time zone from the IANA Database
        tz2 (str): A time zone from the IANA Database

    Returns:
        dict: A dictionary containing result status and 
    """
    dt = datetime.datetime.now()

    try:
        tz1_utc = dt.astimezone(zoneinfo.ZoneInfo(tz1)).utcoffset()
        tz2_utc = dt.astimezone(zoneinfo.ZoneInfo(tz2)).utcoffset()
    except Exception as error:
        return {"result": f"An error occurred: {error}", "delta": None}
    
    tzdiff = (tz2_utc-tz1_utc).total_seconds()/3600
    
    return {"result": "success", "delta": tzdiff}


# Tool to lookup email from registry
@mcp.tool()
def lookup_registry_email(name: str) -> str:
    """Given a name, obtain the email of the individual from the registry API.

    Args:
        name (str): name or approximate name of the person to search for
    
    Returns:
        str: The email address of the person, or an error message if not found
    """
    # URL encode the query parameter
    encoded_query = urllib.parse.quote(name)
    url = f"https://registry.sqprod.co/api/v2/users/search?query={encoded_query}"
    
    # Set headers for the request
    headers = {
        'accept': 'application/json'
    }
    
    try:
        # Make the request to the registry API
        response = requests.get(url, headers=headers)
        
        # Check if the request was successful
        if response.status_code == 200:
            data = response.json()
            
            # Check if any results were returned
            if data and len(data) > 0:
                # Return the email of the first match
                return data[0].get("email", "Email not found in response")
            else:
                return f"No results found for '{name}'"
        else:
            return f"Error: API returned status code {response.status_code}"
    except Exception as e:
        return f"Error making request: {str(e)}"


@mcp.tool()
def retrieve_calendar_events(id: str="primary") -> dict:
    """Given an email, retrieves the calendar events.

    Args:
        id (str): Email address to retrieve calendar events for. Defaults to the user's calendar
        
    Returns:
        result: Dict of call result and list of calendar events for the specified email
    """
    events = []
    try:
        creds = get_gcal_credentials()
    except Exception as error:
        return {"result":f"An error occurred: {error}", "events":events}
    
    try:
        service = build("calendar", "v3", credentials=creds)

        # Call the Calendar API
        now = datetime.datetime.now().isoformat() + "Z"  # 'Z' indicates UTC time
        print("Getting the upcoming 10 events")
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=50,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

    except Exception as error:
        return {"result": f"An error occurred: {error}", "events": events}
    
    return {"result": "success", "events": events}


@mcp.tool()
def retrieve_calendar_free_busy_slots(
        time_min: str,
        time_max: str,
        timezone: str = "UTC",
        ids: list = ["primary"]) -> dict:

    """Retrieves free and busy slots from the calendars of the ids list. 

    Useful to find slots to schedule meetings
    
    Args:
        time_min (str): Starting time in isoformat
        time_max (str): Finish time in isoformat
        timezone (str, optional): The timezone of interest
        ids (list, optional): A list containing emails for the 
        calendars of interest. Defaults to the user's calendar.

    Returns:
        dict: A dictionary containing the free or busy slots for each of the ids requested
    """    
    
    try:
        creds = get_gcal_credentials()
    except Exception as error:
        return {"result": f"An error occurred: {error}", "response": {}}
    
    items = [{"id": x} for x in ids]
    query = {
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": timezone,
        "groupExpansionMax": 2,
        "calendarExpansionMax": 2,
        "items": items
    }
    
    try:
        service = build("calendar", "v3", credentials=creds)
        
        # Call the Calendar API
        response = service.freebusy().query(body=query).execute()
        
    except Exception as error:
        return {"result": f"An error occurred: {error}", "response": {}}
    
    return {"result": "success", "response": response}


@mcp.tool()
def retrieve_timezone(calendar_id: str = "primary") -> dict:
    """Retrieves timezone for a given calendar.
    
    Args:
        id (str, optional): id / email of the calendar of interest. Defaults to the user's calendar

    Returns:
        dict: A dictionary containing the free or busy slots for each of the ids requested
    """ 
    
    try:
        creds = get_gcal_credentials()
    except Exception as error:
        return {"result": f"An error occurred: {error}", "response": {}}
    
    try:
        service = build("calendar", "v3", credentials=creds)
        
        # Call the Calendar API
        response = service.calendars().get(calendarId=calendar_id).execute()
        
    except Exception as error:
        return {"result": f"An error occurred: {error}", "response": {}}
    
    return {"result": "success", "response": response}
