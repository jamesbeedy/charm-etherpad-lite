import os
import socket

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
    unit_private_ip,
    is_leader,
    config,
    local_unit
)

from charmhelpers.core.host import (
    service_running,
    service_start,
    service_restart
)

from charmhelpers.core.templating import render
from charmhelpers.core.unitdata import kv

from charms.layer.nginx import configure_site
from charms.layer import options


opts = options('tls-client')
SRV_KEY = opts.get('server_key_path')
SRV_CRT = opts.get('server_certificate_path')


@when_not('etherpad.systemd.installed')
@when('codebase.available')
def install_etherpad():

    # Render systemd template
    render(source="etherpad.service.tmpl",
           target="/etc/systemd/system/etherpad.service",
           perms=0o644,
           owner="root",
           context={})
    set_state('etherpad.systemd.installed')
    status_set('active', 'Etherpad systemd service ready')


@hook('config-changed')
def config_changed():
    conf = config()
    if conf.changed('port') and conf.previous('port'):
        close_port(conf.previous('port'))
    if conf.get('port'):
        open_port(conf['port'])
    setup()


@when('postgresql.connected')
@when_not('etherpad.db.requested')
def request_etherpad_database(pgsql):
    """Request etherpad db
    """

    status_set('maintenance', 'Requesting PostgreSQL database for Etherpad.')
    # Request database for Etherpad
    if is_leader():
        pgsql.set_database("etherpad")
        # Set active status
    status_set('active', 'PostgreSQL database requested')
    # Set state
    set_state('etherpad.db.requested')


@when_not('etherpad.db.available')
@when('postgresql.master.available')
def get_set_db_data(db):
    unit_data = kv()
    etherpad_db = {}
    etherpad_db['db_name'] = db.master.dbname
    etherpad_db['db_pass'] = db.master.password
    etherpad_db['db_host'] = db.master.host
    etherpad_db['db_user'] = db.master.user
    unit_data.set('db', etherpad_db)
    set_state('etherpad.db.available')


@when('etherpad.db.available', 'codebase.available',
      'etherpad.systemd.available')
@when_not('etherpad.initialized')
def configure_etherpad():
    """Call setup
    """
    setup()
    set_state("etherpad.initialized")


def setup():
    """Gather and write out etherpad configs
    """

    unit_data = kv()
    db = unit_data.get('db')
    if not db:
        status_set('blocked', 'need relation to postgresql')
        return

    settings_target = "/srv/etherpad-lite/settings.json"

    if os.path.exists(settings_target):
        os.remove(settings_target)

    render(source='settings.json.tmpl',
           target=settings_target,
           perms=0o644,
           owner='www-data',
           context=db)

    restart_service()
    status_set('active', 'Etherpad configured')


@when('certificates.available')
def send_data(tls):
    # Use the public ip of this unit as the Common Name for the certificate.
    common_name = unit_public_ip()
    # Get a list of Subject Alt Names for the certificate.
    sans = []
    sans.append(unit_public_ip())
    sans.append(unit_private_ip())
    sans.append(socket.gethostname())
    # Create a path safe name by removing path characters from the unit name.
    certificate_name = local_unit().replace('/', '_')
    # Send the information on the relation object.
    tls.request_server_cert(common_name, sans, certificate_name)


@when('certificates.server.cert.available')
@when_not('etherpad.ssl.available')
def save_crt_key(tls):
    '''Read the server crt/key from the relation object and
    write to /etc/ssl/certs'''

    # Remove the crt/key if they pre-exist
    if os.path.exists(SRV_CRT):
        os.remove(SRV_CRT)
    if os.path.exists(SRV_KEY):
        os.remove(SRV_KEY)

    # Get and write out crt/key
    server_cert, server_key = tls.get_server_cert()

    with open(SRV_CRT, 'w') as crt_file:
        crt_file.write(server_cert)
    with open(SRV_KEY, 'w') as key_file:
        key_file.write(server_key)

    status_set('active', 'TLS crt/key ready')
    set_state('etherpad.ssl.available')


@when('nginx.available', 'etherpad.ssl.available',
      'etherpad.initialized')
@when_not('etherpad.web.configured')
def configure_webserver():
    """Configure nginx
    """

    status_set('maintenance', 'Configuring website')
    configure_site('etherpad', 'etherpad.nginx.tmpl',
                   key_path=SRV_KEY,
                   crt_path=SRV_CRT, fqdn=config('fqdn'))
    open_port(443)
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
