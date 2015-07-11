import collections
import math
import json
import urlparse
import functools
import re
import ftplib
import os
import operator
import md5
import urllib2
import sys

from selenium import webdriver
from nltk import word_tokenize
from nltk.data import path as nltk_path
from nltk.corpus import stopwords
from nltk.stem.porter import PorterStemmer

import config


# NLTK resource initialization
nltk_path.append(config.NLTK_DATA_PATH)
nltk_to_download = []
try:
    stopwords.words('english')
except LookupError:
    nltk_to_download.append('stopwords')
try:
    word_tokenize('token test')
except LookupError:
    nltk_to_download.append('punkt')
if nltk_to_download:
    print 'Performing first-time setup'
    from nltk import download as nltk_download
    for package in nltk_to_download:
        print '\tDownloading:', package
        nltk_download(package)
STOPWORDS = frozenset(stopwords.words('english')) | frozenset('.,:()&[]?%;')
STEMMER = PorterStemmer()

BASE_URL_DOMAIN = urlparse.urlparse(config.BASE_URL).netloc
DISALLOWED_ARTICLE_PATHS = frozenset((
    'Category_Articles_with_hCards', 'Category_Biography_with_signature',
))


TEMPLATE = '''
<!doctype html>
<html>
	<head>
		<meta charset="UTF-8">
		<title>
			{title} - The Chase-Jellison Homestead
		</title>
		<link href="/style.css" rel="stylesheet" media="screen">
        <link href="./style.css" rel="stylesheet" media="screen">
		<script type="text/javascript" src="http://ajax.googleapis.com/ajax/libs/jquery/1.5/jquery.min.js"></script>
		<script type="text/javascript" src="jquery.cycle.all.js"></script>
        <script type="text/javascript" src="signup_onclick.js"></script>
	</head>
	<body>
		<header>
			<!--#include virtual="/header.html"-->
			<div id="header_image">
				<div class="slideshow">
					<img src="/img/header/bw_house_cropped.png" alt="The Chase-Jellison Homestead in winter">
				</div>
			</div>
		</header>
		<div id="content">
			<article id="featured" >
				<div id="centered_content">
					{body}
				</div>
			</article>
		</div>
        <script type="text/javascript">
            function highlight_famtree() {{
                $("table strong.selflink").parent().css('background-color', '#93b0cd');
            }}
            function move_image() {{
                $("td:only-child a.image").detach().prependTo("#mw-content-text");
                $("td:not(:has(*))[colspan]").detach();
            }}
            $(document).ready(highlight_famtree);
            $(document).ready(move_image);
        </script>
		<!--#include virtual="/footer.html"-->
	</body>
</html>
'''


Article = collections.namedtuple('Article', 'path depth title html text')


def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller
    (http://stackoverflow.com/questions/19669640/bundling-data-files-with-pyinstaller-2-1-and-meipass-error-onefile)
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def main():
    if not os.path.exists('rendered'):
        os.mkdir('rendered')

    # Scraping
    driver = webdriver.PhantomJS(
        resource_path('phantomjs.exe'), 
        service_args=[
            '--disk-cache=true', 
            '--max-disk-cache-size=50000'
        ]
    )
    frontier = {'Chase-Jellison_Homestead'}
    visited = set()
    articles = []
    image_urls = set()
    max_depth = 3

    for depth in xrange(max_depth):
        frontier, visited, new_articles, new_images = update(driver, frontier, visited, depth)
        articles.extend(new_articles)
        image_urls |= new_images

    with open('articles.txt', 'w') as f:
        for article in articles:
            f.write(config.BASE_URL + article.path + '\n')

    # Building search index
    print "Building search index"
    k = 2
    document_vectors = {
        url(article.path): dict(collections.Counter(
            STEMMER.stem(word) for word in word_tokenize(article.text.lower()) if word not in STOPWORDS
        ))
        for article in articles
    }
    document_lengths = {
        k: sum(v.itervalues())
        for k, v in
        document_vectors.iteritems()
    }
    all_tokens = {token for document in document_vectors.itervalues() for token in document}
    num_documents = len(document_vectors) + 1.  # Pretend there's one document with no tokens, so no IDF is 0
    average_document_length = sum(document_lengths.itervalues()) / (num_documents - 1)
    idfs = {
        token: math.log(num_documents / sum(token in document for document in document_vectors.itervalues()))
        for token in all_tokens
    }
    document_vectors = {  # Bake-in IDF value
        key: {
            token: value * idfs[token] / (value + (document_lengths[key] / average_document_length))
            for token, value in
            document.iteritems()
        }
        for key, document in
        document_vectors.iteritems()
        if key not in DISALLOWED_ARTICLE_PATHS  # exclude these from index
    }
    
    with open('rendered\\vectors.js', 'w') as f:
        f.write('var vectors = ' + json.dumps(document_vectors))

    # Rendering static pages
    print "Rendering static pages"
    article_paths = frozenset(article.path for article in articles)
    _render_link = functools.partial(render_link, article_paths)
    local_hashes = {}
    for article in articles:
        fixed_links_html = re.sub(
            'href="[^"]+"', 
            _render_link,
            article.html.replace('<span dir="auto">Category:', '<span dir="auto">Category: ')
        ).encode('ascii', 'xmlcharrefreplace')
        fixed_imlinks_html = re.sub(
            'href="[^"]+\.(png|JPG)"',
            '',
            fixed_links_html,
        )
        fixed_imsrcs_html = re.sub(
            'src="/images[^"]+\.(png|JPG)"',
            render_image,
            fixed_imlinks_html
        )
        page = TEMPLATE.format(
            title=article.title.replace('Category:', 'Category: '),
            body=fixed_imsrcs_html,
        )
        with open('rendered\\{}.shtml'.format(url(article.path)), 'w') as f:
            f.write(page)
        local_hashes[url(article.path) + '.shtml'] = md5.md5(page).hexdigest()
    
    article_links = (
        '<li><a href="{}.shtml">{}</a></li>'.format(url(article.path), article.title.replace('Category:', 'Category: '))
        for article in sorted(articles, key=operator.attrgetter('title'))
        if url(article.path) not in DISALLOWED_ARTICLE_PATHS
    )
    index = TEMPLATE.format(
        title='Browse articles', 
        body='<h1>Browse articles</h1><ul id="article_list">{}</ul>'.format('\n'.join(article_links))
    )
    with open('rendered\\index.shtml', 'w') as f:
        f.write(index)
    local_hashes['index.shtml'] = md5.md5(index).hexdigest()

    # Upload articles to server
    print "Connecting to FTP server"
    ftp = ftplib.FTP(config.FTP_SERVER)
    ftp.login(config.FTP_USERNAME, config.FTP_PASSWORD)
    ftp.cwd(config.FTP_TARGET_DIR)

    hashfile_chunks = list()
    server_hashes = {}
    try:
        print "\tDownloading: hashes.json"
        ftp.retrbinary('RETR hashes.json', hashfile_chunks.append)
        server_hashes = json.loads(''.join(hashfile_chunks))
    except ftplib.error_perm:
        print "\t\tWarning: hashes.json not found"
    except ValueError:
        print "\t\tWarning: hashes.json was not a valid JSON file"

    os.chdir('rendered')
    for fname in os.listdir(os.getcwd()):
        if fname == 'hashes.json':
            continue
        file_hash = local_hashes.get(fname)
        if file_hash is None:
            if fname.endswith('.shtml'):
                continue  # No longer current - prior scrape leftover
            with open(fname, 'r') as f:
                file_hash = md5.md5(f.read()).hexdigest()
                local_hashes[fname] = file_hash
        if file_hash == server_hashes.get(fname):
            continue
        with open(fname, 'rb') as f:
            print '\tUploading:', fname
            ftp.storbinary('STOR {}'.format(fname), f)

    with open('hashes.json', 'w') as f:
        json.dump(local_hashes, f)
    if local_hashes != server_hashes:
        with open('hashes.json', 'rb') as f:
            print '\tUploading: hashes.json'
            ftp.storbinary('STOR hashes.json', f)

    # Upload images to server
    ftp.cwd(config.FTP_TARGET_IMG_DIR)
    existing_images = frozenset(ftp.nlst())
    for image_url in image_urls:
        fname = make_relative(image_url)
        if fname in existing_images:
            # assume images are static
            continue
        image = urllib2.urlopen(image_url)
        print '\tTransferring image:', fname
        ftp.storbinary('STOR {}'.format(fname), image)

    raw_input("Finished (enter to quit)")


def url(path):
    '''Simple replacement to make categories work'''
    if path.startswith('http://'):
        return path
    return path.replace(':', '_')


def render_link(article_paths, match):
    relative_link = make_relative(match.group()[6:-1])
    ext = '.shtml' if relative_link in article_paths else ''
    return 'href="{}{}"'.format(url(relative_link), ext)


def render_image(match):
    return 'src="/img/articles/{}"'.format(make_relative(match.group()[6:-1]))


def update(driver, old_frontier, visited, depth):
    print 'Scraping pages within', depth, 'clicks'
    articles = []
    new_frontier = set()
    images = set()
    for page in old_frontier:
        print '\tDownloading:', page
        
        driver.get(config.BASE_URL + page)
        content = get_content(driver)
        article = Article(page, depth, get_title(content), get_html(content), get_text(content))
        
        visited.add(page)
        articles.append(article)
        new_frontier |= get_links(content, visited)
        images |= get_images(content)

    return new_frontier - visited, visited, articles, images


def get_content(driver):
    return driver.find_element_by_xpath(".//div[@id='content']")


def get_title(content):
    return content.find_element_by_xpath(".//h1").text


def get_html(content):
    return content.get_attribute('innerHTML')


def get_text(content):
    content_elements = []
    content_elements.extend(content.find_elements_by_xpath(".//div[@id='mw-content-text']"))
    content_elements.extend(content.find_elements_by_xpath(".//div[@id='mw-normal-catlinks']"))
    return '\n'.join(elem.text for elem in content_elements)


def get_links(content, visited):
    links = (
        make_relative(link.get_attribute('href'))
        for link in
        content.find_elements_by_xpath(".//a[contains(@href, 'index.php/') or contains(@href, 'index.php?title=Category:')]")
    )
    links = {
        link for link in links
        if link not in visited
        and 'File:' not in link
        and 'Special:' not in link
    }
    category_links = (  # Because often these are "red" but wanted
        urlparse.parse_qs(urlparse.urlparse(link.get_attribute('href')).query)['title'][0]
        for link in
        content.find_elements_by_xpath(".//a[contains(@href, 'index.php?title=Category:')]")
    )
    links |= {link for link in category_links if link not in visited}
    return links


def get_images(content):
    return {
        image.get_attribute('src')
        for image in 
        content.find_elements_by_xpath(".//a[@class='image']/img")
    }


def make_relative(href):
    parsed_href = urlparse.urlparse(href)
    if parsed_href.netloc not in {BASE_URL_DOMAIN, 'localhost', ''}:
        return href
    if '?' in href:
        titles = urlparse.parse_qs(parsed_href.query).get('title')
        if titles:
            return titles[0]
        return href
    return parsed_href.path.split('/')[-1]


if __name__ == '__main__':
    main()