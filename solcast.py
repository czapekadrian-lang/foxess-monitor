import os
import requests
import datetime
import json
from zoneinfo import ZoneInfo
from collections import defaultdict

SOLCAST_JSON = "solcast.json"
SOLCAST_DB = "solcast.db"
ESTIMATE_NOMINAL = 'pv_estimate'
ESTIMATE_WORST = 'pv_estimate10'
ESTIMATE_BEST = 'pv_estimate90'

def save_data_to_json(data_to_save: dict, filepath: str):
    with open(filepath, 'w') as json_file:
        json.dump(data_to_save, json_file, indent=4)

def load_data_from_json(filepath: str) -> dict | None:
    with open(filepath, 'r') as json_file:
        data = json.load(json_file)
    return data

def get_solcast_estimate(api_key,id):
  url = f"https://api.solcast.com.au/rooftop_sites/{{{id}}}/forecasts?format=json"
  payload = {}
  headers = {'Content-Type':'application/json; charset=utf-8',
            'Authorization': f"Bearer {api_key}"
           }
  response = requests.request("GET", url, headers=headers, data=payload)

  #Save estimate to solcast file
  if os.path.exists(SOLCAST_JSON):
    forecasts = load_data_from_json(SOLCAST_JSON)
  else:
    forecasts = []
  new_forecast = response.json()
  new_forecast['datetime'] = new_forecast.get('forecasts')[0].get('period_end')
  forecasts.append(new_forecast)
  save_data_to_json(forecasts,SOLCAST_JSON)

#Build solcast.db
def create_solcast_db(json_file,local_tz):
  tz = ZoneInfo(local_tz)
  solcasts = load_data_from_json(json_file)
  solcast_db = {}
  for item in solcasts:
    for forecast in item.get('forecasts'):
      #convert period time to local timezone
      period_end_local = datetime.datetime.fromisoformat(forecast.get('period_end').replace('Z', '+00:00')).astimezone(tz)
      estimates = {
          'pv_estimate':forecast.get('pv_estimate'),
          'pv_estimate10':forecast.get('pv_estimate10'),
          'pv_estimate90':forecast.get('pv_estimate90'),
      }
      solcast_db[period_end_local.isoformat()] = estimates

  return solcast_db

def get_hourly_solcast_for_date(file,estimate_type,date):
  db = load_data_from_json(file)
  hourly_estimate_kwh = defaultdict(float)
  hourly_forecast = {}

  for period, forecast in db.items():
    if period.split("T")[0] == date and forecast.get(estimate_type):
      period_datetime = datetime.datetime.fromisoformat(period)
      hour_of_production = (period_datetime - datetime.timedelta(minutes=1)).hour
      energy = forecast.get(estimate_type) * 0.5
      hourly_estimate_kwh[hour_of_production] += energy

  return hourly_estimate_kwh

def plot_production_with_forecast(forecast,production):
  import matplotlib.pyplot as plt
  import numpy as np

  labels  = list(forecast.keys())
  values1 = list(forecast.values())
  values2 = list(production.values())

  x = np.arange(len(labels))  # the label locations
  width = 0.35  # the width of the bars
  fig, ax = plt.subplots()

  # Plotting the bars
  rects1 = ax.bar(x - width/2, values1, width, label='Forecast', color='#fad105')
  rects2 = ax.bar(x + width/2, values2, width, label='Real', color='gray')


  # Add some text for labels, title and axes ticks
  ax.set_ylabel('Power [kWh]')
  ax.set_xticks(x)
  ax.set_xticklabels(labels)
  ax.legend()

  # Removing the top and right part of the frame
  ax.spines['top'].set_visible(False)
  ax.spines['right'].set_visible(False)

  def add_labels(rects):
      """Attach a text label above each bar in *rects*, displaying its height."""
      for rect in rects:
          height = rect.get_height()
          if height > 0.0:
            ax.annotate(f'{height:.2f}',
                      xy=(rect.get_x() + rect.get_width() / 2, height),
                      xytext=(0, 3),  # 3 points vertical offset
                      textcoords="offset points",
                      ha='center', va='bottom', rotation=90,
                      fontsize=8) # Using a smaller font size

  # Add labels to both sets of bars
  add_labels(rects1)
  add_labels(rects2)

  fig.tight_layout()

  return fig, ax