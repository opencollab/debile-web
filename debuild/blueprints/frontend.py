# Copyright (c) 2012 Paul Tagliamonte <paultag@debian.org>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from flask import Blueprint, render_template, send_file
from sqlalchemy.orm import joinedload
from lucy.orm import Package, Source, Binary, Machine, User, Job, Group
from lucy.config import Config
from lucy.server import Session

from humanize import naturaltime
from humanize.time import naturaldelta

from datetime import timedelta
import datetime as dt
import os.path


frontend = Blueprint('frontend', __name__, template_folder='templates')


@frontend.app_template_filter('seconds_display')
def seconds_display(time):
    td = timedelta(seconds=time)
    return naturaldelta(td)


@frontend.app_template_filter('ago')
def ago_display(when):
    if when is None:
        return "never"
    td = dt.datetime.utcnow() - when
    return naturaltime(td)


@frontend.app_template_filter('location')
def location_display(obj):
    if obj is None:
        return ""

    fo = obj['file']
    po = obj['point']

    if po is None:
        return fo['givenpath']

    return "%s:%s" % (obj['file']['givenpath'],
                      obj['point']['line'])


@frontend.route("/")
def index():
    session = Session()
    active_jobs = session.query(Job).filter(Job.machine != None).filter(Job.finished_at == None).all()
    machines = session.query(Machine).options(joinedload('jobs')).all()
    # TODO : Disable fred builds query for now
    #pending = fred_db.builds.find()
    return render_template('about.html', **{
        "active_jobs": active_jobs,
        "machines": machines,
    })


@frontend.route("/sources/")
def source_list():
    session = Session()
    count = 1
    sources = session.query(Source).options(joinedload(Source.user)).options(joinedload(Source.jobs)).options(joinedload(Source.group)).order_by(Source.updated_at.desc()).limit(count)

    return render_template('source_list.html', **{
        "sources": sources,
        "count": count,
    })


@frontend.route("/group/<group_id>/")
@frontend.route("/group/<group_id>/<page>/")
def group_list(group_id, page=0):
    page = int(page)
	# FIXME : unsafe code, catch exceptions
    session = Session()
    g = session.query(Group).filter(Group.name == group_id).one()
    sources = session.query(Source).filter(Source.group == g).order_by(Source.updated_at.asc()).paginate(page, per_page=15)

    return render_template('group.html', **{
        "sources": sources,
        "group_id": group_id,
        "page": page,
    })


@frontend.route("/source/<package_id>/")
def source(package_id):
    session = Session()
    # FIXME : unsafe code, catch exceptions
    package = session.query(Source).filter(Source.package_id == package_id).one()
    total = session.query(Job).filter(Job.package == package).count()
    unfinished = session.query(Job).filter(Job.package == package).filter(Job.finished_at == None).count()
    return render_template('source.html', **{
        "package": package,
        "package_job_status" : (total, unfinished)
    })


@frontend.route("/machine/<machine_id>/")
def machine(machine_id):
    session = Session()
    # FIXME : unsafe code, catch exceptions
    machine = session.query(Machine).filter(Machine.id == machine_id).one()
    return render_template('machine.html', **{
        "machine": machine
    })


@frontend.route("/hacker/<hacker_id>/")
def hacker(hacker_id):
    session = Session()
	# FIXME : unsafe code, catch exceptions
    user = session.query(User).filter(User.id == user_id).one()
    return render_template('hacker.html', **{
        "hacker": user
    })


@frontend.route("/report/<job_id>/")
def report(job_id):
# TODO : design architecture Pending, firewose ?
#    report = Report.load(report_id)
    config = Config()
    log_path = os.path.join(config.get('paths', 'job'),
                        job_id, 'log')

    flink = "/report/firehose/%s/" % job_id
    loglink = "/report/log/%s/" % job_id

    log = []
    if os.path.exists(log_path):
        log = (x.decode('utf-8') for x in open(log_path, 'r'))

    return render_template('report.html', **{
        "log_link": loglink,
        "firehose_link": flink,
        "log": log,
    })

@frontend.route("/report/firehose/<job_id>/")
def report_firehose(job_id):
    config = Config()
    firehose_path = os.path.join(config.get('paths', 'job'),
                        job_id, 'firehose.xml')

    if os.path.exists(firehose_path):
        return send_file(firehose_path, mimetype='application/xml', as_attachment=True, attachment_filename='firehose.xml')

@frontend.route("/report/log/<job_id>/")
def report_log(job_id):
    config = Config()
    log_path = os.path.join(config.get('paths', 'job'),
                        job_id, 'log')

    if os.path.exists(log_path):
        return send_file(log_path, mimetype='text/plain', as_attachment=True, attachment_filename='log.txt')
