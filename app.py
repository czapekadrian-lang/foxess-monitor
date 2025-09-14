import os
import requests
import hashlib
import time
import json
import datetime
import random
import threading
from zoneinfo import ZoneInfo
import plotly.graph_objects as go
from flask import Flask, render_template, request

# --- API Settings ---
API_KEY = os.environ.get("API_KEY")
SN = os.environ.get("SN")
STATION_ID = os.environ.get("STATION_ID")
BASE_URL = "https://www.foxesscloud.com"

# --- Shared state variable ---
shared_state = {
    'init_soc':20,
    'charge_start_hour':None,
    'forecast_offset':None,
}
lock = threading.Lock()

# Other settings
MAX_RETRY = 5
volt_threshold = 253

# Other Variables


# --- FOXESS API functions ---
def create_headers(api_key, path):
    timestamp = str(round(time.time() * 1000))
    signature_string = fr"{path}\r\n{api_key}\r\n{timestamp}"
    signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest()
    return {
        'Content-Type': 'application/json', 'token': api_key, 'signature': signature,
        'timestamp': timestamp, 'timezone': "Europe/Warsaw", 'lang': "en",
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

def post(path, params):
    url = BASE_URL + path
    headers = create_headers(API_KEY, path)
    try:
        response = requests.post(url, headers=headers, json=params)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        print(f"API request failed: {e}")
        return None

def get(path,params):
    url = BASE_URL + path

    # Create headers
    headers = create_headers(API_KEY,path)

    try:
        # Make the POST request
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

        return response

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        print("Status Code:", response.status_code)
        print("Response Text:", response.text)
    except Exception as err:
        print(f"An other error occurred: {err}")

def get_device_history_data(serial_number, variables, start, end):
    path = "/op/v0/device/history/query"
    params = {"variables": variables, "sn": serial_number, "begin": start, "end": end}
    return post(path, params)

def api_get_plant_detail(stationID):
    path = "/op/v0/plant/detail"

    # Set up the request parameters
    params = {
        "id": stationID,
    }
    return get(path,params)

def get_device_realtime_data(serial_number,variables):
    path = "/op/v1/device/real/query"
    sns = []
    sns.append(serial_number)

    params ={
        "variables" : variables,
        "sns" : sns,
    }

    return post(path,params)

def get_setting(sn,key):
    path = "/op/v0/device/setting/get"

    params ={
        "sn" : sn,
        "key" : key,
    }

    return post(path,params)

def set_setting(sn,key,value):
    path = "/op/v0/device/setting/set"

    params ={
        "sn" : sn,
        "key" : key,
        "value" : value,
    }

    return post(path,params)
# --- End of FOXESS API functions

# --- Function calculate kWh from power data (series of power in kW)
def calculate_kwh(power_data, start_time_str, end_time_str):
    processed_data = []
    for entry in power_data:
        try:
            full_time_str = entry['time']
            dt_part, tz_part = full_time_str.rsplit(' ', 1)
            tz_offset = tz_part[-5:]
            clean_time_str = dt_part + tz_offset
            reliable_format = '%Y-%m-%d %H:%M:%S%z'
            time_obj = datetime.datetime.strptime(clean_time_str, reliable_format)
            processed_data.append({'time': time_obj, 'value': entry['value']})
        except (ValueError, IndexError):
            print(f"Skipping entry with unparsable time: {entry['time']}")

    if not processed_data: return 0.0
    processed_data.sort(key=lambda x: x['time'])

    first_entry_tz = processed_data[0]['time'].tzinfo
    start_time = datetime.datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=first_entry_tz)
    end_time = datetime.datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=first_entry_tz)

    total_kwh = 0.0
    for i in range(len(processed_data) - 1):
        current_point = processed_data[i]
        next_point = processed_data[i+1]
        if current_point['time'] >= start_time and next_point['time'] <= end_time:
            time_delta_seconds = (next_point['time'] - current_point['time']).total_seconds()
            time_delta_hours = time_delta_seconds / 3600.0
            power_kw = float(next_point['value'])
            energy_kwh = power_kw * time_delta_hours
            total_kwh += energy_kwh
    return total_kwh

# --- Prepare data for sankey diagram ---
def plot_diagram(power_data, date):
    data = {
     'Calculated Load Power': power_data['Calculated Load Power'], 'Feed-in Power': power_data['Feed-in Power'],
     'GridConsumption Power': power_data['GridConsumption Power'], 'Discharge Power': power_data['Discharge Power'],
     'Charge Power': power_data['Charge Power'], 'PVPower': power_data['PVPower'],
     'PV Auto Consume Power': power_data['PV Auto Consume Power']
    }
    label_keys_map = {
        'PV Power': 'PVPower', 'Grid Consumption': 'GridConsumption Power', 'Discharge Power': 'Discharge Power',
        'Calculated Load Power': 'Calculated Load Power', 'PV Auto Consume Power': 'PV Auto Consume Power',
        'Charge Power': 'Charge Power', 'Feed-in Power': 'Feed-in Power'
    }
    original_labels = list(label_keys_map.keys())
    labels_with_values = [f"{label}: {data[label_keys_map[label]]:.3f}" for label in original_labels]

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=25, thickness=20, line=dict(color="black", width=0.5), label=labels_with_values,
            color=["#2ca02c", "#d62728", "#ff7f0e", "#1f77b4", "#9467bd", "#8c564b", "#e377c2"],
            x=[0.01, 0.4, 0.4, 0.99, 0.4, 0.4, 0.4], y=[0.3, 0.05, 0.3, 0.4, 0.55, 0.8, 1]
        ),
        link=dict(
            source=[0, 0, 0, 4, 2, 1], target=[4, 5, 6, 3, 3, 3],
            value=[
                data['PV Auto Consume Power'], data['Charge Power'], data['Feed-in Power'],
                data['PV Auto Consume Power'], data['Discharge Power'], data['GridConsumption Power']
            ]
        )
    )])
    fig.update_layout(title_text=f"Power Flow Diagram ({date})", font_size=12, width=800, height=600)
    return fig

# --- Sankey diagram generate ---
def generate_sankey_for_date(date_selected):
    """Wraps the entire process for a given date and returns a Plotly figure."""
    try:
        year, month, day = map(int, date_selected.split('-'))
        variables = ["loadsPower", "feedinPower", "gridConsumptionPower", "batDischargePower", "batChargePower", "pvPower","generationPower"]

        tz = ZoneInfo("Europe/Warsaw")
        startdate = datetime.datetime(year, month, day, 0, 0, 0, tzinfo=tz)
        enddate = datetime.datetime(year, month, day, 23, 59, 59, tzinfo=tz)

        response = get_device_history_data(SN, variables, startdate.timestamp() * 1000, enddate.timestamp() * 1000)
        if not response: return "Failed to retrieve data from API."

        datas = response.json().get('result')[0].get('datas')
        for entry in datas:
            dt_object = datetime.datetime.strptime(entry['data'][0].get('time')[:-10], "%Y-%m-%d %H:%M:%S")
            first_item = {'time': f"{dt_object.replace(minute=0, second=0, microsecond=0)} CEST+0200", 'value': 0.000}
            entry['data'].insert(0, first_item)

        calculated_data = {}
        for variable in datas:
            power_data = variable.get('data')
            start_str = str(datetime.datetime(year, month, day, 0, 0, 0))
            end_str = str(datetime.datetime(year, month, day, 23, 59, 59))
            total_kwh = calculate_kwh(power_data, start_str, end_str)
            calculated_data.update({variable.get('name'): round(total_kwh, 3)})

        #Waste calculation and update PVPower with calculated waste
        pv_waste = calculated_data['PVPower'] + calculated_data['Discharge Power'] - calculated_data['Charge Power'] - calculated_data['Output Power']
        grid_waste = calculated_data['Load Power'] - calculated_data['Output Power'] - calculated_data['GridConsumption Power'] + calculated_data['Feed-in Power']
        pv_power = calculated_data['PVPower'] - pv_waste + grid_waste
        calculated_data.update({'PVPower':round(pv_power,3)})

        pv_autoconsume = calculated_data['PVPower'] - calculated_data['Charge Power'] - calculated_data['Feed-in Power']

        calculated_load = pv_autoconsume + calculated_data['Discharge Power'] + calculated_data['GridConsumption Power']

        delta_load = calculated_load - calculated_data['Load Power']

        calculated_data.update({"PV Auto Consume Power" : round(pv_autoconsume,3)})
        calculated_data.update({"Calculated Load Power" : round(calculated_load,3)})
        calculated_data.update({"PV Waste Power" : round(pv_waste,3)})
        calculated_data.update({"Grid Waste Power" : round(grid_waste,3)})
        calculated_data.update({"Delta Load Power" : round(delta_load,3)})

        return plot_diagram(calculated_data, date_selected), calculated_data

    except Exception as e:
        # Return an error message string if anything goes wrong
        return f"An error occurred: {e}"

def get_charge_start_hour_from_rce(target_date):

    base_url = "https://api.raporty.pse.pl/api/rce-pln"
    odata_filter = f"business_date eq '{target_date}' and period ge '07:00' and period lt '17:00'"
    params = {
        '$filter': odata_filter
    }

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()

        lowest_entry = min(data.get('value'), key=lambda x: x['rce_pln'])
        highest_entry = max(data.get('value'), key=lambda x: x['rce_pln'])
        lowest_rce = float(lowest_entry.get('rce_pln'))
        highest_rce = float(highest_entry.get('rce_pln'))
        threshold_rce = (lowest_rce - highest_rce) / highest_rce * 0.9 * highest_rce
        threshold_rce += highest_rce

        for entry in data.get('value'):
            if entry.get('rce_pln') < threshold_rce:
                utc_tz = datetime.timezone.utc
                period_utc = entry.get("period_utc")
                start_utc_str, end_utc_str = period_utc.split(' - ')
                target_date_obj = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
                start_utc = datetime.datetime.strptime(start_utc_str, '%H:%M').time()
                end_utc = datetime.datetime.strptime(end_utc_str, '%H:%M').time()
                start_datetime = datetime.datetime.combine(target_date_obj, start_utc)
                end_datetime = datetime.datetime.combine(target_date_obj, end_utc)
                start_datetime_utc = start_datetime.replace(tzinfo=utc_tz)
                end_datetime_utc = end_datetime.replace(tzinfo=utc_tz)
                start_datetime_local = start_datetime_utc.astimezone(tzInfo)
                end_datetime_local = end_datetime_utc.astimezone(tzInfo)
                period_cest = f"{start_datetime_local.strftime('%H:%M')} - {end_datetime_local.strftime('%H:%M')}"
                #print(f"Na podstawie cen RCE, zalecane rozpoczęcie ładowania baterii w dniu {target_date}: {period_cest}")
                break

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")

    return int(start_datetime_local.strftime('%H'))

def select_work_mode(init_charge,soc,rvolt,svolt,tvolt):
    charge_star_hour = int(os.environ.get("CHARGE_START_HOUR")) + int(os.environ.get("FORECAST_OFFSET"))
    if init_charge:
        print("SoC below 20%, init charge in progress")
        return "SelfUse"

    if soc < 15 or rvolt >= 253 or svolt >= 253 or tvolt >= 253:
        print("Parameters out of range")
        return "SelfUse"

    hour_now = int(datetime.datetime.now(tzInfo).strftime('%H'))
    if hour_now < charge_star_hour:
        print(f"Time to Export {hour_now} < {charge_star_hour}")
        return "Feedin"
    else:
        print(f"Time to Self-Use {hour_now} >= {charge_star_hour}")
        return "SelfUse"


def get_plant_detail(station_id):
    for attempt in range(MAX_RETRY):
        try:
            response = api_get_plant_detail(station_id)
            response.raise_for_status()
            break

        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRY - 1:
                print("API call failed. No more tried. Exiting.")
                response = None
                break

            wait_time = (2 ** attempt) + random.uniform(0, 1)
            print(f"API call failed. Waiting for {wait_time:.2f} seconds before retrying...")
            time.sleep(wait_time)

    return response

# --- WorkMode Algorithm loop
def workmode_algorithm():
    global shared_state
    print("WorkMode thread executed")
    while True:

        #Get current settings
        with lock:
            init_soc = shared_state['init_soc']

        print (init_soc)

        time.sleep(5)

# --- Flask App Initialization ---
app = Flask(__name__)
# --- Flask Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    # Calculate today's date in the required YYYY-MM-DD format
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    if request.method == 'POST':
        date_selected = request.form['date']
        result = generate_sankey_for_date(date_selected)

        if isinstance(result, str): # Handle error case
            return render_template('index.html', error=result, selected_date=date_selected, today_date=today_str)
        else: # Handle success case
            # Unpack the tuple into two variables
            fig, calc_data = result
            plot_div = fig.to_html(full_html=False)
            # Pass the calculated_data to the template
            return render_template('index.html', plot_div=plot_div, calculated_data=calc_data, selected_date=date_selected, today_date=today_str)
    
    # For a GET request, pass today's date for both the default value and the max date
    return render_template('index.html', selected_date=today_str, today_date=today_str)

plant_detail = get_plant_detail(STATION_ID)
timezone = plant_detail.json()['result']['timezone']
tzInfo = ZoneInfo(timezone)
print(tzInfo)

if __name__ == '__main__':
    workmode_thread = threading.Thread(target = workmode_algorithm, daemon = True)
    workmode_thread.start()
    app.run(debug = True, use_reloader = False)
