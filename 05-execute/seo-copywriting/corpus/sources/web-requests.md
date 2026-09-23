Title: Requests project landing/readme
Published: 2017
Genre: web-copy
Tone: direct, practical, confident
SHA256: a57e258dc0a3f200e254f6dc88f7eea3994a065c7e6d07e616c76c8bc5d8e855

---

Requests: HTTP for Humans
=========================

.. image:: 
    :target: 

.. image:: 
    :target: 

.. image:: 
    :target: 

.. image:: 
    :target: 
    :alt: codecov.io

.. image:: 
    :target: 

.. image:: 
    :target: 



Requests is the only *Non-GMO* HTTP library for Python, safe for human
consumption.

**Warning:** Recreational use of the Python standard library for HTTP may result in dangerous side-effects,
including: security vulnerabilities, verbose code, reinventing the wheel,
constantly reading documentation, depression, headaches, or even death.

Behold, the power of Requests:

.. code-block:: python

    >>> r = requests.get(' auth=('user', 'pass'))
    >>> r.status_code
    200
    >>> r.headers['content-type']
    'application/json; charset=utf8'
    >>> r.encoding
    'utf-8'
    >>> r.text
    u'{"type":"User"...'
    >>> r.json()
    {u'disk_usage': 368627, u'private_gists': 484, ...}

See the similar code, sans Requests.

.. image:: 
    :target: 


Requests allows you to send *organic, grass-fed* HTTP/1.1 requests, without the
need for manual labor. There's no need to manually add query strings to your
URLs, or to form-encode your POST data. Keep-alive and HTTP connection pooling
are 100% automatic, thanks to urllib3.

Besides, all the cool kids are doing it. Requests is one of the most
downloaded Python packages of all time, pulling in over 11,000,000 downloads
every month. You don't want to be left out!

Feature Support
---------------

Requests is ready for today's web.

- International Domains and URLs
- Keep-Alive & Connection Pooling
- Sessions with Cookie Persistence
- Browser-style SSL Verification
- Basic/Digest Authentication
- Elegant Key/Value Cookies
- Automatic Decompression
- Automatic Content Decoding
- Unicode Response Bodies
- Multipart File Uploads
- HTTP(S) Proxy Support
- Connection Timeouts
- Streaming Downloads
- ``.netrc`` Support
- Chunked Requests

Requests officially supports Python 2.6–2.7 & 3.3–3.7, and runs great on PyPy.

Installation
------------

To install Requests, simply:

.. code-block:: bash

    $ pip install requests
    ✨🍰✨

Satisfaction guaranteed.

Documentation
-------------

Fantastic documentation is available at  for a limited time only.


How to Contribute
-----------------

#. Check for open issues or open a fresh issue to start a discussion around a feature idea or a bug. There is a `Contributor Friendly`_ tag for issues that should be ideal for people who are not very familiar with the codebase yet.
#. Fork `the repository`_ on GitHub to start making your changes to the **master** branch (or branch off of it).
#. Write a test which shows that the bug was fixed or that the feature works as expected.
#. Send a pull request and bug the maintainer until it gets merged and published. :) Make sure to add yourself to AUTHORS_.

.. _`the repository`: 
.. _AUTHORS: 
.. _Contributor Friendly:
