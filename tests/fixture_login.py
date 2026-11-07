import msvcrt
import sys
import time

email = sys.argv[sys.argv.index('--email')+1]
if email == 'hang@example.com':
    time.sleep(15)
if email == 'cancel@example.com':
    sys.exit(0)
print('Email  Password  ctrl+s log in', flush=True)
received = ''
while not received.endswith('\x13'):
    received += msvcrt.getwch()
if received != '\tp&ass中文\x13':
    print('Error: unexpected terminal input', flush=True)
    sys.exit(2)
if email == 'wrong@example.com':
    print('Error: Incorrect email or password', flush=True)
    sys.exit(1)
print('Logged in successfully.', flush=True)
