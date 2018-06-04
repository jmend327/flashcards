#! /usr/bin/python
# This app acts as flashcards, without the need for a server or paper cards!

import csv
import pprint
import random
import pandas
import json
import sys
from openpyxl import Workbook


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


def get_flashcard_file():
	try:
		return sys.argv[1]
	except:
		return 'flashcard_sets/sports.xlsx'


def get_filetype(flashcard_file):
	return flashcard_file.split(".")[-1:][0]


def get_flashcard_set(filename, filetype):
	# Returns a filename of the flashcards file. For this example, it's 
	# the 'flashcards.csv' file.

	if filetype == 'csv':
		reader = csv.DictReader(open(filename, 'rb'))
		for row in reader:
			flashcards_json.append(row)
		return flashcards_json

	if filetype == 'xlsx':
		return json.loads(pandas.read_excel(filename).to_json(orient='records'))


def study_flashcards_session(flashcards_json_list):
	# Conducts a flashcard study session. This prompts a question to the user, asks 
	# if their answer was successfull, and updates the question "score" accordingly.

	def choose_question():
		# For now, rendomly generates and returns a number (question ID).
		return random.choice(flashcards_json_list)

	def update_score(question_json, success):
		# Updates the question score based on run.
		return

	while True:
		print "\n----------\n"
		success_criteria = ''
		question_json = choose_question()

		while success_criteria != "y":
			
			user_input = raw_input("Question: " + question_json["Question"] + "\nYour Answer: ")
			
			if user_input == "quit":
				break

			print "\033[1m\033[92m\nAnswer:\n\033[0m" + str(question_json["Answer"])

			success_criteria = raw_input("\nWas your answer correct? (y/n): ")

			print "\n"
			
		if user_input == "quit":
			break



def end_study_session(json_list,filename,filetype):
	print "Finished study session, saving " + str(filename)

	if filetype == "xlsx":
		pandas.read_json(json.dumps(json_list), orient='records').to_excel("saved_flashcards.xlsx")

	print "Done."


def main():
	flashcard_file = get_flashcard_file()
	flashcard_filetype = get_filetype(flashcard_file)

	flashcard_set_list_jsons = get_flashcard_set(flashcard_file,flashcard_filetype)

	study_flashcards_session(flashcard_set_list_jsons)

	#end_study_session(flashcard_set_list_jsons,flashcard_file,flashcard_filetype)
	print "Done with study session."


if __name__ == '__main__':
	main()


