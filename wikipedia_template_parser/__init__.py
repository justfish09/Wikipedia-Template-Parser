"""
Wikipedia-Template-Parser
A simple library for extracting data from Wikipedia templates
"""

import re
import requests
import logging
import urllib
from pyquery import PyQuery as pq
import mwparserfromhell
import sys

logger = logging.getLogger(__name__)

if sys.version_info[0] < 3:
    string = basestring
    unquote = urllib.unquote
    quote = urllib.quote
else:
    string = str
    unquote = urllib.parse.unquote
    quote = urllib.parse.quote


def clean_wiki_links(s):
    """
    Given a wiki text removes links syntax
    Examples: [[Page]] -> Page
              [[Page|displayed text]] -> displayed text
    """
    # clean links without renaming
    s = re.sub(r'\[\[([^\|\]]+)\]\]', r'\1', s)
    # clean links with renaming
    s = re.sub(r'\[\[[^\|\]]+\|([^\]]+)\]\]', r'\1', s)
    return s


def clean_ref(s):
    """
    Cleans <ref> tags
    """
    text = pq(s)
    res = []
    for el in text.contents():
        if isinstance(el, string):
            res.append(el.strip())
        elif el.tag != "ref":
            res.append(clean_ref(el))
    return " ".join(res)


def get_wikitext_from_api(page, lang='en'):
    """
    Given a page title and the language returns the wiki text of the latest
    revision of the page
    """
    url = 'http://{}.wikipedia.org/w/api.php'.format(lang)
    params = {
        'action': 'query',
        'prop': 'revisions',
        'titles': unquote(page.replace(' ', '_')),
        'rvprop': 'content',
        'rvlimit': '1',
        'format': 'json',
        'redirects': True
    }
    res = requests.get(url, params=params)
    if not res.ok:
        res.raise_for_status()
    json_pages = res.json()['query']['pages']

    try:
        result = list(json_pages.values())[0]['revisions'][0]['*']
    except:
        raise ValueError('Page {page} does not exist on '
                         '{lang}.wikipedia'.format(page=page, lang=lang))

    return result


def extract_data_from_coord(template):
    coord = {'lat': '', 'lon': ''}
    optionalpars = ['dim',
                    'globe',
                    'region',
                    'scale',
                    'source',
                    'type',
                    'display'
                    ]

    todel = set()
    for k, v in template.items():
        for op in optionalpars:
            if (op in v) or (op in k):
                todel.add(k)
                break

    for k in todel:
        del template[k]

    anonpars = [tpar for tpar in template.keys() if 'anon_' in tpar]
    for ap in anonpars:
        template[int(ap.strip('anon_'))] = template[ap]
        del template[ap]

    parsnums = [int(p.strip('anon_')) for p in anonpars]
    parcount = len(anonpars)
    startpar = min(parsnums)

    gglat = float(template[startpar])
    mmlat = 0
    sslat = 0
    gglong = 0
    mmlong = 0
    sslong = 0
    dirlat = ''
    dirlong = ''
    if parcount == 2:
        gglong = float(template[startpar+1])
    elif parcount == 4:
        dirlat = str(template[startpar+1])
        gglong = float(template[startpar+2])
        dirlong = str(template[startpar+3])
    elif parcount == 6:
        mmlat = float(template[startpar+1])
        dirlat = str(template[startpar+2])
        gglong = float(template[startpar+3])
        mmlong = float(template[startpar+4])
        dirlong = str(template[startpar+5])
    elif parcount == 8:
        mmlat = float(template[startpar+1])
        sslat = float(template[startpar+2])
        dirlat = str(template[startpar+3])
        gglong = float(template[startpar+4])
        mmlong = float(template[startpar+5])
        sslong = float(template[startpar+6])
        dirlong = str(template[startpar+7])

    deglat = float(gglat)+float(mmlat)/60.0+float(sslat)/3600.0
    deglong = float(gglong)+float(mmlong)/60.0+float(sslong)/3600.0

    if dirlat == "S":
        deglat = - deglat
    if dirlong == "W":
        deglong = - deglong

    coord['lat'] = str(deglat)
    coord['lon'] = str(deglong)
    return coord


def augment_data_with_coords(data, coords_fiels):
    from coordinates import parseDMS

    wanted_fields = [field for sublist in coords_fiels for field in sublist]

    values = [data.get(field, '') for field in wanted_fields]

    if not any(values):
        return False

    try:
        coords_data = parseDMS(*values)[0]
        data['lon'] = coords_data['dec-long']
        data['lat'] = coords_data['dec-lat']
    except:
        logger.exception("Can't find coordinates")


CURLY = re.compile(r'\{\{([^\}]*)\}\}')


def data_from_templates(page, lang='en', extra_coords=None, wikitext=None):
    """
    Given a page title and the language returns a list with the data of every
    template included in the page.
    Every list item is a dictionary with 2 keys: name and data. name is the
    name of the template while data is a dictionary with key/value attributes
    of the template.
    """
    store = []
    if wikitext is None:
        content = ' '.join(get_wikitext_from_api(page, lang).split())
    else:
        content = ' '.join(wikitext.split())
    #match = re.findall(r'\{\{([^}]+)\}\}', content)
    match = mwparserfromhell.parse(content).filter_templates()
    for template_string in match:
        template_string = template_string[2:-2]
        template_string = clean_ref(template_string)
        anon_counter = 0
        template_string = clean_wiki_links(template_string)
        if CURLY.search(template_string):
            for match in CURLY.finditer(template_string):
                start = match.start()
                stop = match.end()
                template_string = template_string[:start] + '{{' + \
                    match.group(1).replace('|', '~') + '}}' + \
                    template_string[stop:]

        template_string = template_string.split("|")
        name, key_values = template_string[0].strip(), template_string[1:]
        data = {}
        for key_value in key_values:
            try:
                key, value = key_value.split("=", 1)
            except ValueError:
                anon_counter += 1
                key = 'anon_{}'.format(anon_counter)
                value = key_value
            data[key.strip()] = value.strip()
        cleaned_name = name.lower().replace('_', ' ')
        if cleaned_name == 'coord':
            data = extract_data_from_coord(data)
        if extra_coords:
            if cleaned_name in extra_coords:
                augment_data_with_coords(data, extra_coords[cleaned_name])

        store.append({'name': name, 'data': data})
    return store


def pages_with_template(template, lang='en', eicontinue=None,
                        skip_users_and_templates=True):
    """
    Returns a list of pages that use the given template

    template is something like 'Template:Infobox_museum'

    skip_users_and_templates allows you to skip users and templates page like
    * http://en.wikipedia.org/wiki/User:<name>
    * http://en.wikipedia.org/wiki/User_talk:<name>
    * http://en.wikipedia.org/wiki/Template:<name>
    * http://en.wikipedia.org/wiki/Template_talk:<name>
    """
    url = 'http://{}.wikipedia.org/w/api.php'.format(lang)
    skip_page = None

    if skip_users_and_templates:
        skip_page = (
            'user:',
            'utente:',

            'user_talk:'
            'discussioni_utente:',

            'template:',

            'template_talk:',
            'discussioni_template:',
        )

    params = {
        'action': 'query',
        'list': 'embeddedin',
        'eititle': template,
        'eilimit': 500,
        'format': 'json',
    }
    if eicontinue:
        params['eicontinue'] = eicontinue
    res = requests.get(url, params=params)
    if not res.ok:
        res.raise_for_status()

    if skip_users_and_templates:
        result = [x['title'] for x in res.json()['query']['embeddedin']
                  if not x['title'].lower().startswith(skip_page)
                 ]
    else:
        result = [x['title'] for x in res.json()['query']['embeddedin']]

    try:
        eicontinue = res.json()['query-continue']['embeddedin']['eicontinue']
    except KeyError:
        eicontinue = None
    if eicontinue:
        result += pages_with_template(
            template,
            lang,
            eicontinue,
            skip_users_and_templates
        )
    return result


def pages_in_category(catname, lang='en', maxdepth=0,
                      cmcontinue=None, subcats=None, visitedcats=None):
    """
    Returns a list of pages in a given category and its subcategories
    parameters:
    catname: category name with prefix (e.g. "Categoria:Chiese_di_Prato")
    lang: Wikipedia language code (e.g. "it"), optional (default is "en")
    maxdepth: specifies the number (a non-negative integer) of levels
              to descend at most in the category tree starting from catname.
    """
    url = 'http://{}.wikipedia.org/w/api.php'.format(lang)
    params = {
        'action': 'query',
        'list': 'categorymembers',
        'cmtitle': catname,
        'cmlimit': '500',
        'format': 'json'
    }
    if visitedcats is None:
        visitedcats = list()
    if cmcontinue:
        params['cmcontinue'] = cmcontinue
    res = requests.get(url, params=params)
    if not res.ok:
        res.raise_for_status()
    result = [x['title'].encode('utf-8')
              for x in res.json()['query']['categorymembers']
              if x['ns'] == 0
             ]
    subcats = [x['title'].replace(' ', '_')
               for x in res.json()['query']['categorymembers']
               if x['ns'] == 14 and x['title'] not in visitedcats]
    try:
        query_continue = res.json()['query-continue']
        cmcontinue = query_continue['categorymembers']['cmcontinue']
    except KeyError:
        cmcontinue = None
    if cmcontinue:
        result += pages_in_category(catname,
                                    lang=lang,
                                    maxdepth=maxdepth,
                                    cmcontinue=cmcontinue,
                                    subcats=subcats,
                                    visitedcats=visitedcats)
    maxdepth -= 1
    if maxdepth >= 0:
        if subcats:
            for cat in subcats:
                result += pages_in_category(cat,
                                            lang=lang,
                                            maxdepth=maxdepth,
                                            cmcontinue=cmcontinue,
                                            subcats=subcats,
                                            visitedcats=visitedcats)
                visitedcats.append(cat)
    return result


if __name__ == "__main__":
    print(get_wikitext_from_api("Chiesa di San Petronio", "it"))
    print(data_from_templates("Volano_(Italia)", "it"))
    print(data_from_templates("Cattedrale di San Vigilio", "it"))
    print(data_from_templates("Telenorba", "it"))
    print(data_from_templates("Pallavolo Falchi Ugento", "it"))
    pisa_text = get_wikitext_from_api("Torre pendente di Pisa", "it")
    tmpl_from_text = data_from_templates("Torre pendente di Pisa",
                                         lang="it",
                                         wikitext=pisa_text
                                         )
    tmpl_from_api = data_from_templates("Torre pendente di Pisa", "it")
    if tmpl_from_text == tmpl_from_api:
        print("Templates from text and from API match")
    else:
        print("W00t?!")
