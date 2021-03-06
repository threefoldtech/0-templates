from jumpscale import j
from zerorobot.template.base import TemplateBase
from zerorobot.template.state import StateCheckError
from zerorobot.service_collection import ServiceNotFoundError

ZERODB_TEMPLATE_UID = 'github.com/threefoldtech/0-templates/zerodb/0.0.1'
NODE_CLIENT = 'local'


class Vdisk(TemplateBase):

    version = '0.0.1'
    template_name = "vdisk"

    def __init__(self, name=None, guid=None, data=None):
        super().__init__(name=name, guid=guid, data=data)
        self.add_delete_callback(self.uninstall)
        self.recurring_action('_monitor', 10)
        if not self.data.get('password'):
            self.data['password'] = j.data.idgenerator.generateXCharID(32)

    def validate(self):
        try:
            # ensure that a node service exists
            node = self.api.services.get(template_account='threefoldtech', template_name='node')
            node.state.check('actions', 'install', 'ok')
        except:
            raise RuntimeError("not node service found, can't install the namespace")

        for param in ['diskType', 'size', 'label']:
            if not self.data.get(param):
                raise ValueError("parameter '%s' not valid: %s" % (param, str(self.data[param])))

    @property
    def _node_sal(self):
        """
        connection to the node
        """
        return j.clients.zos.get(NODE_CLIENT)

    @property
    def _zerodb(self):
        return self.api.services.get(template_uid=ZERODB_TEMPLATE_UID, name=self.data['zerodb'])

    def _monitor(self):
        self.state.check('actions', 'install', 'ok')

        try:
            self._zerodb.state.check('status', 'running', 'ok')
            self.state.set('status', 'running', 'ok')
        except StateCheckError:
            data = {
                    'attributes': {},
                    'resource': self.guid,
                    'text': 'Failed to start vdisk {}'.format(self.name),
                    'environment': 'Production',
                    'severity': 'critical',
                    'event': 'Hardware',
                    'tags': [],
                    'service': ['vdisk']
                }
            alertas = self.api.services.find(template_uid='github.com/threefoldtech/0-templates/alerta/0.0.1')
            for alerta in alertas:
                alerta.schedule_action('send_alert', args={'data': data})
            self.state.delete('status', 'running')

    def install(self):
        try:
            # no op is already installed
            self.state.check('actions', 'install', 'ok')
            return
        except StateCheckError:
            pass

        node = self.api.services.get(template_account='threefoldtech', template_name='node')
        kwargs = {
            'disktype': self.data['diskType'],
            'mode': 'user',
            'password': self.data['password'],
            'public': False,
            'ns_size': int(self.data['size']),
        }
        # use the method on the node service to create the zdb and the namespace.
        # this action hold the logic of the capacity planning for the zdb and namespaces
        self.data['zerodb'], self.data['nsName'] = node.schedule_action('create_zdb_namespace', kwargs).wait(die=True).result

        zerodb_data = self._zerodb.data.copy()
        zerodb_data['name'] = self._zerodb.name
        zerodb_sal = self._node_sal.primitives.from_dict('zerodb', zerodb_data)

        disk = self._node_sal.primitives.create_disk(self.data['nsName'],
                                                     zerodb_sal,
                                                     mountpoint=self.data['mountPoint'] or None,
                                                     filesystem=self.data['filesystem'] or None,
                                                     size=int(self.data['size']),
                                                     label=self.data['label'])
        disk.deploy()

        self.state.set('actions', 'install', 'ok')
        self.state.set('status', 'running', 'ok')

    def info(self):
        self.state.check('actions', 'install', 'ok')
        return self._zerodb.schedule_action('namespace_info', args={'name': self.data['nsName']}).wait(die=True).result

    def url(self):
        self.state.check('actions', 'install', 'ok')
        return self._zerodb.schedule_action('namespace_url', args={'name': self.data['nsName']}).wait(die=True).result

    def private_url(self):
        self.state.check('actions', 'install', 'ok')
        return self._zerodb.schedule_action('namespace_private_url', args={'name': self.data['nsName']}).wait(die=True).result

    def uninstall(self):
        self._zerodb.schedule_action('namespace_delete', args={'name': self.data['nsName']}).wait(die=True)
        self.state.delete('actions', 'install')
        self.state.delete('status', 'running')
