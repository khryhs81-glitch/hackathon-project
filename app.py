# app.py
from flask import Flask, request, jsonify, send_from_directory
from lottery import run_lottery  # Import your lottery logic

# Create the Flask app
app = Flask(__name__, static_folder="static")  # static folder contains index.html

# Route to serve the HTML form
@app.route("/")
def home():
    return send_from_directory("static", "index.html")

# Route to handle form submissions
@app.route("/submit", methods=["POST"])
def submit():
    # Receive data from frontend as JSON
    student_data = request.json
    print("Received data:", student_data)

    # Call your lottery logic
    assigned_classes = run_lottery(student_data)

    # Return results as JSON
    return jsonify({"status": "ok", "assigned_classes": assigned_classes})

# Run the Flask server
if __name__ == "__main__":
    app.run(debug=True)
