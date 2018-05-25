from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello():
	return "Hello World!"


@app.route("/sets/")
def sets():
	return "TODO: Interact with flashcard sets"


if __name__ == '__main__':
	app.run(debug=True)