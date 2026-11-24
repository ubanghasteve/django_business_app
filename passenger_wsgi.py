import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INTERP = '/home/abgpycyd/virtualenv/business_app/3.10/bin/python'
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'business_app.settings')

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()