import re

line_stripped = '15 Airport Road, Lugbe, F.C.T, Abuja, Nigeria Tel: +234 07014 676 188'

clean_line = line_stripped

# Method 1: Split by Tel:, Phone:, Mobile:, Email:
for sep in ['Tel:', 'Phone:', 'Mobile:', 'Email:']:
    if sep in clean_line:
        clean_line = clean_line.split(sep)[0].strip()
        print(f'After split: {repr(clean_line)}')
        break

# Check what happens next in the code
print(f'clean_line after all processing: {repr(clean_line)}')
print(f'Pattern match: {re.match(r"^\d+\s+\w+", clean_line)}')

street_types = ['street', 'st', 'avenue', 'ave', 'road', 'rd', 'drive', 'dr', 
               'lane', 'ln', 'court', 'ct', 'place', 'pl', 'boulevard', 'blvd',
               'close', 'way', 'crescent', 'cres']
print(f'Street type found: {any(st in clean_line.lower() for st in street_types)}')

# What the code should do:
if re.match(r'^\d+\s+\w+', clean_line):
    if any(st in clean_line.lower() for st in street_types):
        print('Should return:', clean_line)
