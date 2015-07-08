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

from selenium import webdriver
from nltk import word_tokenize
from nltk.data import path as nltk_path
from nltk.corpus import stopwords
from nltk.stem.porter import PorterStemmer

import config


BASE_URL_DOMAIN = urlparse.urlparse(config.BASE_URL).netloc
nltk_path.append(config.NLTK_DATA_PATH)
STEMMER = PorterStemmer()
STOPWORDS = frozenset(stopwords.words('english')) | frozenset('.,:()&[]?%;')

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


def main():
    # Scraping
    driver = webdriver.PhantomJS(
        'bin/phantomjs.exe', 
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
    document_vectors = {
        url(article.path): dict(collections.Counter(
            STEMMER.stem(word) for word in word_tokenize(article.text.lower()) if word not in STOPWORDS
        ))
        for article in articles
    }
    all_tokens = {token for document in document_vectors.itervalues() for token in document}
    num_documents = len(document_vectors)
    idfs = {
        token: math.log(num_documents / (sum(token in document for document in document_vectors.itervalues()) + 1.))  # Laplace smoothing to avoid division by zero
        for token in all_tokens
    }
    document_vectors = {  # Bake-in IDF value
        key: {
            token: value * idfs[token]
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
    index = TEMPLATE.format(title='Browse articles', body='<h1>Browse articles</h1><ul>{}</ul>'.format('\n'.join(article_links)))
    with open('rendered\\index.shtml', 'w') as f:
        f.write(index)

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

    print "Finished"


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