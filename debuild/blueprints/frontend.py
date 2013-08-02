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
    count = 10
    sources = session.query(Source)\
        .options(joinedload(Source.user))\
        .options(joinedload(Source.group))\
        .order_by(Source.updated_at.desc())\
        .limit(count)
    sources_info = []
    for s in sources:
        info = {}
        info['source'] = s
        info['source_link'] = "/source/%s/%s/%s/%s" % (s.user.login, s.name, s.version, s.run)
        info['group_link'] = "/group/%s" % s.group.name
        info['user_link'] = "/hacker/%s" % s.user.login
        sources_info.append(info)


    return render_template('source_list.html', **{
        "sources_info": sources_info,
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


@frontend.route("/source/<owner_name>/<package_name>/<package_version>/<int:run_number>")
def source(package_name, owner_name, package_version, run_number):
    session = Session()

    # Let's compute all the versions that exists for this package
    versions_query = session.query(Source.version)\
	    .join(Source.user)\
        .filter(Source.name == package_name)\
        .filter(User.login == owner_name)
    versions = sorted(set([e[0] for e in versions_query.all()]))

    print versions
    latest_version = versions[-1]
    if package_version == 'latest':
        this_version = latest_version
    else:
        this_version = package_version

    # All runs that exist for this version
    runs_query = session.query(Source.run)\
	    .join(Source.user)\
        .filter(Source.name == package_name)\
        .filter(User.login == owner_name)\
        .filter(Source.version == this_version)\
        .order_by(Source.run.asc())
    runs = [e[0] for e in runs_query.all()]

    print runs
    latest_run = runs[-1]
    if run_number == '0':
        this_run = latest_run
    else:
        this_run = run_number

    # Join load the user to show details about the source owner
    package_query = session.query(Source)\
        .options(joinedload('user'))\
        .options(joinedload('jobs'))\
        .options(joinedload('binaries'))\
        .filter(Source.name == package_name)\
        .filter(User.login == owner_name)\
        .filter(Source.version == this_version)\
        .filter(Source.run == this_run)

    try:
        package = package_query.one()
    except (NoResultFound, MultipleResultsFound):
        raise Exception("This resource does not exist")

    # Compute description section
    desc = {}
    desc['user_link'] = "/hacker/%s" % package.user.login
    desc['run'] = run_number
    # desc['pool_link'] =

    # Fill in the run sections if need be
    # Remember that multiple runs cannot exist with fred auto-build
    if len(runs) > 1:
        multiple_runs = True
    else:
        multiple_runs = False
    runs_info = []
    if multiple_runs:
        for r in runs:
            href = "/source/%s/%s/%s/%s" % (owner_name, package_name, package_version, r)
            runs_info.append((r, href))

    # Fill in the version sections
    if len(versions) > 1:
        multiple_versions = True
    else:
        multiple_versions = False
    versions_info = []
    if multiple_versions:
        for v in versions:
            if owner_name == 'fred':
                href = "/sources/%s/%s" % (package_name, v)
            else:
                href = "/sources/%s/%s/%s" % (owner_name, package_name, v)
            versions_info.append((v, href))

    # Compute infos to display the job parts
    # Iterate through all jobs
    # Job total counters + compute some links
    source_jobs = session.query(Job)\
        .options(joinedload('machine'))\
        .filter(Job.package == package)\
        .all()

    total = len(source_jobs)
    unfinished = 0
    source_jobs_info = []
    for j in source_jobs:
        info = {}
        info['job'] = j
        info['job_link'] = '/report/%s' % j.uuid
        if j.machine:
            info['job_machine_link'] = '/machine/%s' % j.machine.name
        if not j.is_finished():
            unfinished += 1
            if j.machine is None:
                info['status'] = 'pending'
            else:
                info['status'] = 'running'
        else:
            info['status'] = 'finished'

        source_jobs_info.append(info)

    binaries_jobs = session.query(Job)\
        .options(joinedload('machine'))\
        .join(Binary, Job.package_id == Binary.package_id)\
        .filter(Binary.source_id == package.source_id)\
        .all()

    binaries_jobs_info = []
    for j in binaries_jobs:
        info = {}
        info['job'] = j
        info['job_link'] = '/report/%s' % j.uuid
        if j.machine:
            info['job_machine_link'] = '/machine/%s' % j.machine.name
        if not j.is_finished():
            unfinished += 1
            if j.machine:
                info['status'] = 'running'
            else:
                info['status'] = 'pending'
        else:
            info['status'] = 'finished'
            binaries_jobs_info.append(info)

    return render_template('source.html', **{
        "desc": desc,
        "multiple_runs": multiple_runs,
        "runs_info": runs_info,
        "latest_run": latest_run,
        "multiple_versions": multiple_versions,
        "latest_version": latest_version,
        "versions_info": versions_info,
        "package": package,
        "package_job_status" : (total, unfinished),
        "source_jobs_info": source_jobs_info,
        "binaries_jobs_info": binaries_jobs_info
    })


@frontend.route("/machine/<machine_name>/")
def machine(machine_name):
    session = Session()
    # FIXME : unsafe code, catch exceptions
    machine = session.query(Machine).filter(Machine.name == machine_name).one()
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


@frontend.route("/report/<job_uuid>/")
def report(job_uuid):
# TODO : design architecture Pending, firewose ?
#    report = Report.load(report_id)
    config = Config()
    session = Session()
    job_query = session.query(Job).filter(Job.uuid == job_uuid)
    try:
        job = job_query.one()
    except (NoResultFound, MultipleResultsFound):
        raise Exception("This resource does not exist")

    job_info = {}
    job_info['job'] = job
    job_info['job_runtime'] = job.finished_at - job.assigned_at
    job_info['package_link'] = '/source/%s/%s/%s/%s/' % (job.package.user.login, job.package.name, job.package.version, job.package.run)

    log_path = os.path.join(config.get('paths', 'job'),
                        job_id, 'log')

    flink = "/report/firehose/%s/" % job_id
    loglink = "/report/log/%s/" % job_id

    log = []
    if os.path.exists(log_path):
        log = (x.decode('utf-8') for x in open(log_path, 'r'))

    return render_template('report.html', **{
        "job_info": job_info,
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
