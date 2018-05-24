#! /usr/bin/python
# This app acts as flashcards, without the need for a server or paper cards!

import csv
import pprint



'''TODO:
	Create server for interaction with browser
	Create tags and allow that as parameter (-tags tag1 tag2 ...)
	Input filename (-f, -n) or set name (-set)
	Have yaml map set names to files
	Create scorecard with Passes, Fails, and Pct
'''


def get_flashcard_set():
	# Returns a filename of the flashcards file. For this example, it's 
	# the 'flashcards.csv' file.
	
	flashcard_set = 'flashcards.csv'
	return flashcard_set

def convert_to_json(flashcard_set):
	# Converts the flashcard csv to json for easy workability/editing.
	flashcards_json = []

	reader = csv.DictReader(open(flashcard_set, 'rb'))
	for row in reader:
		flashcards_json.append(row)
	return flashcards_json

def check_params():
	# Ensures that each question contains a question, answer, pass, and fail field.
	return formatted_flashcards_json

def study_flashcards_session(flashcards_json):
	# Conducts a flashcard study session. This prompts a question to the user, asks 
	# if their answer was successfull, and updates the question "score" accordingly.

	def choose_question():
		# For now, rendomly generates and returns a number (question ID).
		return question_id

	def prompt_question(question_id):
		# Prints the question, and prompts the user for an answer.
		return

	def evaluate_answer():
		# Prints the question's answer and asks the user if their answer was correct.
		return

	def update_score(question_id):
		# Updates the question score based on run.
		return

	practice_question(choose_question())

	return flashcards_json

def convert_json_to_csv():
	return flashcards_csv


def main():
	flashcard_set = get_flashcard_set()
	flashcards_json = convert_to_json(flashcard_set)
	
	pprint.pprint(flashcards_json)

	#study_flashcards_session(flashcards_json)
	#convert_json_to_csv(flashcards_json)

if __name__ == '__main__':
	main()


