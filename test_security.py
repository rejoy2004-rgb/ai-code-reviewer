# test_security.py

password = "admin123"

user_input = input("command: ")

eval(user_input)

import os
os.system(user_input)