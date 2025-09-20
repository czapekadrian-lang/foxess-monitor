import os
import io
import base64
import requests
import hashlib
import time
import json
import datetime
import solcast
from zoneinfo import ZoneInfo
import plotly.graph_objects as go
from flask import Flask, render_template, request, jsonify

# --- Flask App Initialization ---
app = Flask(__name__)

# --- API Settings (FoxESS) ---
API_KEY = os.environ.get("API_KEY")
SN = os.environ.get("SN")
BASE_URL = "https://www.foxesscloud.com"

# --- API Settings (Solcast) ---
SOLCAST_API_KEY = os.environ.get("SOLCAST_API_KEY")
SOLCAST_ID = os.environ.get("SOLCAST_ID")

# --- Helper Functions (Your existing functions, unchanged) ---
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

def get_device_history_data(serial_number, variables, start, end):
    path = "/op/v0/device/history/query"
    params = {"variables": variables, "sn": serial_number, "begin": start, "end": end}
    return post(path, params)

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
        if current_point['time'] >= start_time - datetime.timedelta(seconds=270) and next_point['time'] <= end_time:
            time_delta_seconds = (next_point['time'] - current_point['time']).total_seconds()
            time_delta_hours = time_delta_seconds / 3600.0
            power_kw = float(next_point['value'])
            energy_kwh = power_kw * time_delta_hours
            total_kwh += energy_kwh
    return total_kwh

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
    fig.update_layout(title_text=f"Power Flow Diagram ({date})", font_size=12, height=600, autosize=True)
    return fig

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

# --- Flask Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    # Calculate today's date in the required YYYY-MM-DD format
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    return render_template('index.html', selected_date=today_str, today_date=today_str)

@app.route('/api/powerflow', methods=['POST'])
def api_powerflow():
    """
    Generate PowerFlow diagram data
    """
    # Read frontend data
    data = request.get_json()
    date_selected = data.get('date')

    if not date_selected:
        return jsonify({'error': 'Missing date'}), 400

    result = generate_sankey_for_date(date_selected)

    if isinstance(result, str): # Error handling
        return jsonify({'error': result}), 500
    else: # Success
        fig, calc_data = result
        fig_dict = fig.to_dict()
        
        return jsonify({
            'plot_data': fig_dict['data'],
            'plot_layout': fig_dict['layout'],
            'calculated_data': calc_data
        })

@app.route('/api/production_forecast', methods=['GET'])
def production_forecast():
    timezone = "Europe/Warsaw"
    db = solcast.create_solcast_db(solcast.SOLCAST_JSON,timezone)
    solcast.save_data_to_json(db,solcast.SOLCAST_DB)

    date = datetime.date.today().strftime("%Y-%m-%d")
    nominal = solcast.get_hourly_solcast_for_date(solcast.SOLCAST_DB,solcast.ESTIMATE_NOMINAL,date)
    worst = solcast.get_hourly_solcast_for_date(solcast.SOLCAST_DB,solcast.ESTIMATE_WORST,date)
    best = solcast.get_hourly_solcast_for_date(solcast.SOLCAST_DB,solcast.ESTIMATE_BEST,date)
    
    variables = ["pvPower"]
    startdate = datetime.datetime.strptime(date+" 00:00:00","%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Europe/Warsaw"))
    enddate = datetime.datetime.strptime(date+" 23:59:59","%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Europe/Warsaw"))

    response = get_device_history_data(SN,variables,startdate.timestamp()*1000,enddate.timestamp()*1000)
    pvPower = response.json().get('result')[0].get('datas')[0].get('data')
    forecast = nominal
    real = dict.fromkeys(forecast.keys(), 0.0)
    year,month,day = date.split("-")
    for hour in real.keys():
        start = datetime.datetime(int(year), int(month), int(day), int(hour), 0, 0,tzinfo=ZoneInfo("Europe/Warsaw")).strftime("%Y-%m-%d %H:%M:%S")
        end = datetime.datetime(int(year), int(month), int(day), int(hour), 59, 59,tzinfo=ZoneInfo("Europe/Warsaw")).strftime("%Y-%m-%d %H:%M:%S")
        kwh = round(calculate_kwh(pvPower,start,end),3)
        real[hour] = kwh
    fig, ax = solcast.plot_production_with_forecast(forecast,real)  
    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)
    image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    image_data_url = f"data:image/png;base64,{image_base64}"

    return jsonify({
        'graph_data':image_data_url
    })

@app.route('/api/forecast_update', methods=['GET'])
def forecast_update():
    solcast.get_solcast_estimate(SOLCAST_API_KEY,SOLCAST_ID)

if __name__ == '__main__':
    app.run(debug=True)

