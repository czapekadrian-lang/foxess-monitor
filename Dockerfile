# 1. Start with an official Python base image
FROM python:3.10-slim

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the rest of your application code into the container
COPY . .

# 5. Expose the port that Gunicorn will run on
EXPOSE 5000

# 6. Define the command to run your application using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
