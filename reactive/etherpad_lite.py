import os

from charms.reactive import (
    hook,
    when,
    when_not,
    set_state,
)

from charmhelpers.core.hookenv import (
    status_set,
    close_port,
    open_port,
    unit_public_ip,
    config,
)

from charmhelpers.core.host import (
    service_running,
    service_start,
    service_restart,
    chownr
)

from charmhelpers.core.templating import render
from charmhelpers.core.unitdata import kv

from charms.layer.nginx import configure_site
from charms.layer import options


@when_not('etherpad.systemd.installed')
def install_etherpad():

    # Render systemd template
    render(source="etherpad.service.tmpl",
           target="/etc/systemd/system/etherpad.service",
           perms=0o644,
           owner="root",
           context={})
    set_state('etherpad.systemd.installed')
    status_set('active', 'Etherpad systemd service ready')


@when('db.connected')
@when_not('etherpad.db.requested')
def request_etherpad_database(db):
    """Request etherpad db
    """

    status_set('maintenance', 'Requesting PostgreSQL database for Etherpad.')
    # Request database for Etherpad
    db.set_database("etherpad")
    # Set active status
    status_set('active', 'PostgreSQL database requested')
    # Set state
    set_state('etherpad.db.requested')


@when_not('etherpad.initialized')
@when('db.master.available')
def get_set_db_data(db):

    settings_target = os.path.join(config('app-path'), 'settings.json')
    settings_tmpl = os.path.join(config('app-path'), 'settings.json.template')

    if os.path.exists(settings_target):
        os.remove(settings_target)
    if os.path.exists(settings_tmpl):
        os.remove(settings_tmpl)

    render(source='settings.json.tmpl',
           target=settings_target,
           perms=0o644,
           owner='www-data',
           context={'db_name': db.master.dbname,
                    'db_host': db.master.host,
                    'db_port': db.master.port,
                    'db_user': db.master.user,
                    'db_pass': db.master.password})
    # Set perms
    chownr(path='/var/www', owner='www-data', group='www-data')
    set_state('etherpad.initialized')
    status_set('active', 'Etherpad initialized')


@when('nginx.available', 'etherpad.initialized')
@when_not('etherpad.web.configured')
def configure_webserver():
    """Configure nginx
    """

    status_set('maintenance', 'Configuring website')
    configure_site('etherpad', 'etherpad.nginx.tmpl')
    open_port(80)
    restart_service()
    status_set('active', 'Etherpad available: %s' % unit_public_ip())
    set_state('etherpad.web.configured')


@when('etherpad.web.configured')
def set_status_persist():
    """Set status to persist over other layers
    """
    status_set('active', 'Etherpad available: %s' % unit_public_ip())


def restart_service():
    if service_running("etherpad"):
        service_restart("etherapd")
    else:
        service_start("etherpad")


@when('website.available')
def setup_website(website):
    conf = config()
    website.configure(conf['port'])
