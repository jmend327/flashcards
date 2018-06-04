#! /usr/bin/python
# This app acts as flashcards, without the need for a server or paper cards!

import csv
import pprint
import random
import pandas
import json


'''TODO:
	Create server for interaction with browser
	Create tags and allow that as parameter (-tags tag1 tag2 ...)
	Input filename (-f, -n) or set name (-set)
	Have yaml map set names to files
	Create scorecard with Passes, Fails, and Pct
'''


def check_params():
	# Ensures that each question contains a question, answer, pass, and fail field.
	return

def get_flashcard_set():
	# Returns a filename of the flashcards file. For this example, it's 
	# the 'flashcards.csv' file.

	def get_flashcard_file():
		return 'flashcard_sets/sports.xlsx'

	def get_filetype(flashcard_file):
		return flashcard_file.split(".")[-1:][0]

	def convert_to_json(filename, filetype):
		# Converts the flashcard csv to json for easy workability/editing.

		if filetype == 'csv':
			reader = csv.DictReader(open(filename, 'rb'))
			for row in reader:
				flashcards_json.append(row)
			return flashcards_json

		if filetype == 'xlsx':
			return json.loads(pandas.read_excel(filename).to_json(orient='records'))

	flashcard_filename = get_flashcard_file()

	return convert_to_json(flashcard_filename,get_filetype(flashcard_filename))


def study_flashcards_session(flashcards_json_list):
	# Conducts a flashcard study session. This prompts a question to the user, asks 
	# if their answer was successfull, and updates the question "score" accordingly.

	def choose_question():
		# For now, rendomly generates and returns a number (question ID).
		return random.choice(flashcards_json_list)

	def update_score(question_id, success):
		# Updates the question score based on run.
		return

	while True:
		print "\n----------\n"
		question_json = choose_question()
		user_input = raw_input("Question: " + question_json["Question"] + "\nYour Answer: ")
		
		if user_input == "quit":
			break

		print "\nAnswer:\n" + str(question_json["Answer"])

		success_criteria = raw_input("\nWas your answer correct? (y/n): ")

		if success_criteria == "quit":
			break

def convert_json_to_csv():
	return flashcards_csv


def main():
	flashcard_set_list_jsons = get_flashcard_set()

	study_flashcards_session(flashcard_set_list_jsons)
	#convert_json_to_csv(flashcards_json)

if __name__ == '__main__':
	main()


