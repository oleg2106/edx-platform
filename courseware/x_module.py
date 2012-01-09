class XModule(object):
    ''' Implements a generic learning module. 
        Initialized on access with __init__, first time with state=None, and
        then with state
    '''
    id_attribute='name' # An attribute guaranteed to be unique

    def get_xml_tags():
        ''' Tags in the courseware file guaranteed to correspond to the module '''
        return []
        
    def get_state(self):
        return ""

    def get_score(self):
        return None

    def max_score(self):
        return None

    def get_html(self):
        return "Unimplemented"

    def get_init_js(self):
        ''' JavaScript code to be run when problem is shown. Be aware
        that this may happen several times on the same page
        (e.g. student switching tabs). Common functions should be put
        in the main course .js files for now. ''' 
        return ""

    def get_destroy_js(self):
        return ""

    def handle_ajax(self, dispatch, get):
        ''' dispatch is last part of the URL. 
            get is a dictionary-like object ''' 
        return ""

    def __init__(self, xml, item_id, ajax_url=None, track_url=None, state=None):
        ''' In most cases, you must pass state or xml'''
        self.xml=xml
        self.item_id=item_id
        self.ajax_url=ajax_url
        self.track_url=track_url
        self.state=state
