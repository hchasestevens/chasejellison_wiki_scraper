from selenium import webdriver
import collections


BASE_URL = 'http://chasejellison.no-ip.org/index.php/'
DEBUG = True


Article = collections.namedtuple('Article', 'path depth html text')


def main():
    driver = webdriver.PhantomJS('bin/phantomjs.exe')
    frontier = ['Category:South_Berwick_Families']
    visited = set()
    articles = []
    max_depth = 3

    for depth in xrange(max_depth):
        frontier, visited, new_articles = update(driver, frontier, visited, depth)
        articles.extend(new_articles)



def update(driver, old_frontier, visited, depth):
    if DEBUG:
        print depth, len(old_frontier)
    articles = []
    new_frontier = set()
    for i, page in enumerate(old_frontier):
        driver.get(BASE_URL + page)
        content = get_content(driver)
        article = Article(page, depth, get_html(content), get_text(content))
        
        visited.add(page)
        articles.append(article)
        new_frontier |= get_links(content, visited)

        if DEBUG:
            print '\t', len(new_frontier)

    return new_frontier, visited, articles


def get_content(driver):
    return driver.find_element_by_xpath(".//div[@id='content']")


def get_html(content):
    return content.get_attribute('innerHTML')


def get_text(content):
    content_elements = []
    content_elements.extend(content.find_elements_by_xpath(".//div[@id='mw-content-text']"))
    content_elements.extend(content.find_elements_by_xpath(".//div[@id='mw-normal-catlinks']"))
    return '\n'.join(elem.text for elem in content_elements)


def get_links(content, visited):
    links = (
        link.get_attribute('href').split('/')[-1]
        for link in
        content.find_elements_by_xpath(".//a[contains(@href, 'index.php/')]")
    )
    return {
        link for link in links
        if link not in visited
        and 'File:' not in link
    }



if __name__ == '__main__':
    main()