# Start with an official Python base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port that Gunicorn will run on
EXPOSE 5000

# Define the command to run your application using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]


# Start with an official Python base image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Install Nginx and Supervisor
RUN apt-get update && apt-get install -y nginx supervisor

# Copy config files
RUN rm /etc/nginx/sites-enabled/default
COPY nginx.conf /etc/nginx/sites-available/default
RUN ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port
EXPOSE 80

# Run Supervisor
CMD ["/usr/bin/supervisord"]