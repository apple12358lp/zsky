#encoding:utf-8
#我本戏子2017.7
import sys
reload(sys)
sys.setdefaultencoding('utf-8')

import time
import os
import datetime
import logging
from flask import Flask,request,render_template,session,g,url_for,redirect,flash,current_app,jsonify,send_from_directory
from flask_login import LoginManager,UserMixin,current_user, login_required,login_user,logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_script import Manager, Shell
from flask_migrate import Migrate, MigrateCommand
from flask_wtf import FlaskForm
from wtforms import StringField,PasswordField,SubmitField,BooleanField,TextField
from wtforms.validators import DataRequired,Length,EqualTo,ValidationError
from flask_moment import Moment
from flask_babelex import Babel
from flask_admin import helpers, AdminIndexView, Admin, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from getpass import getpass
from flask_caching import Cache
from werkzeug.security import generate_password_hash,check_password_hash
import jieba
import jieba.analyse
import pymysql
#from flask_debugtoolbar import DebugToolbarExtension

# Initialize Flask and set some config values
app = Flask(__name__)
app.config['DEBUG']=True
app.config['SECRET_KEY'] = 'super-secret'
#debug_toolbar=DebugToolbarExtension()
#debug_toolbar.init_app(app)
#app.config['DEBUG_TB_INTERCEPT_REDIRECTS']=False
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@127.0.0.1:3306/zsky'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True
app.config['SQLALCHEMY_POOL_SIZE']=5000
db = SQLAlchemy(app)
manager = Manager(app)
migrate = Migrate(app, db)
moment=Moment(app)
babel = Babel(app)
app.config['BABEL_DEFAULT_LOCALE'] = 'zh_CN'
loginmanager=LoginManager()
loginmanager.init_app(app)
loginmanager.session_protection='strong'
loginmanager.login_view='login'
loginmanager.login_message = "请先登录！"
cache = Cache(app,config = {
    'CACHE_TYPE': 'redis',
    'CACHE_REDIS_HOST': '127.0.0.1',
    'CACHE_REDIS_PORT': 6379,
    'CACHE_REDIS_DB': '',
    'CACHE_REDIS_PASSWORD': ''
})
cache.init_app(app)



class LoginForm(FlaskForm):
    name=StringField('用户名',validators=[DataRequired(),Length(1,32)])
    password=PasswordField('密码',validators=[DataRequired(),Length(1,20)])
    #rememberme = BooleanField('记住我')
    #submit=SubmitField('登录')
    #def validate_login(self, field):
    #    user = self.get_user()
    #    if user is None:
    #        raise ValidationError('用户名错误！')
    #    if not check_password_hash(user.password, self.password.data):
    #        raise ValidationError('密码错误！')
    def get_user(self):
        return db.session.query(User).filter_by(name=self.name.data).first()


class SearchForm(FlaskForm):
    search = StringField(validators = [DataRequired(message= '请输入关键字')],render_kw={"placeholder":"搜索电影,软件,图片,资料,番号...."})
    submit = SubmitField('搜索')

class Search_Filelist(db.Model):
    """ 这个表可以定期清空数据 """
    __tablename__ = 'search_filelist'
    info_hash = db.Column(db.String(40), primary_key=True,nullable=False)
    file_list = db.Column(db.Text,nullable=False)

class Sphinx_Counter(db.Model):
    """ 索引记录 """
    __tablename__ = 'sphinx_counter'
    counter_id  = db.Column(db.Integer,primary_key=True)
    max_doc_id  = db.Column(db.Integer)

class Search_Hash(db.Model,UserMixin):
    __tablename__ = 'search_hash'
    id = db.Column(db.Integer,primary_key=True,nullable=False,autoincrement=True)
    info_hash = db.Column(db.String(40),unique=True)
    category = db.Column(db.String(20))
    data_hash = db.Column(db.String(32))
    name = db.Column(db.String(200),index=True)
    extension = db.Column(db.String(20))
    classified = db.Column(db.Boolean())
    source_ip = db.Column(db.String(20))
    tagged = db.Column(db.Boolean(),default=False)
    length = db.Column(db.BigInteger)
    create_time = db.Column(db.DateTime,default=datetime.datetime.now)
    last_seen = db.Column(db.DateTime,default=datetime.datetime.now)
    requests = db.Column(db.Integer)
    comment = db.Column(db.String(100))
    creator = db.Column(db.String(20))

class Search_Keywords(db.Model):
    """ 首页推荐 """
    __tablename__ = 'search_keywords'
    id = db.Column(db.Integer,primary_key=True,nullable=False,autoincrement=True)
    keyword = db.Column(db.String(20),nullable=False,unique=True)
    order = db.Column(db.Integer,nullable=False)

class Search_Statusreport(db.Model):
    """ 爬取统计 """
    __tablename__ = 'search_statusreport'
    id = db.Column(db.Integer, primary_key=True,nullable=False,autoincrement=True)
    date = db.Column(db.DateTime,nullable=False,default=datetime.datetime.now)
    new_hashes = db.Column(db.Integer,nullable=False)
    total_requests = db.Column(db.Integer,nullable=False)
    valid_requests = db.Column(db.Integer,nullable=False)
    
class Search_Tags(db.Model):
    """ 搜索记录 """
    __tablename__ = 'search_tags'
    id = db.Column(db.Integer,primary_key=True,nullable=False,autoincrement=True)
    tag = db.Column(db.String(100),nullable=False,unique=True)

class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True,autoincrement=True)
    email = db.Column(db.String(100),nullable=False)
    name = db.Column(db.String(100),unique=True,nullable=False)
    password = db.Column(db.String(200),nullable=False)
    def is_authenticated(self):
        return True
    def is_active(self):
        return True
    def is_anonymous(self):
        return False
    def get_id(self):
        return self.id
    def __unicode__(self):
        return self.username


@loginmanager.user_loader
def load_user(id):
    return User.query.get(int(id))


@app.route('/',methods=['GET','POST'])
#@cache.cached(60*60*24)
def index():
    conn = pymysql.connect(host='127.0.0.1',port=9306,user='root',password='',db='film',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
    curr = conn.cursor()
    totalsql='select count(*) from film'
    curr.execute(totalsql)
    totalcounts=curr.fetchall()
    total=int(totalcounts[0]['count(*)'])
    todaysql='SELECT DAY(create_time) AS day,count(*) FROM film  GROUP BY day ORDER BY day limit 1'
    curr.execute(todaysql)
    todaycounts=curr.fetchall()
    today=int(todaycounts[0]['count(*)'])
    curr.close()
    conn.close()
    keywords=Search_Keywords.query.order_by(Search_Keywords.order).all()
    form=SearchForm()
    return render_template('index.html',form=form,keywords=keywords,total=total,today=today)


def make_cache_key(*args, **kwargs):
    path = request.path
    args = str(hash(frozenset(request.args.items())))
    return (path + args).encode('utf-8')

def todate_filter(s):
    return datetime.datetime.fromtimestamp(int(s)).strftime('%Y-%m-%d')
app.add_template_filter(todate_filter,'todate')

@app.route('/search',methods=['GET','POST'])
def search():
    form=SearchForm()
    if not form.search.data:
        return redirect(url_for('index'))
    return redirect(url_for('search_results',query=form.search.data))

@app.route('/main-search-kw-<query>.html',methods=['GET','POST'])
#@cache.cached(timeout=60*60,key_prefix=make_cache_key)
def search_results(query=None):
    connzsky = pymysql.connect(host='127.0.0.1',port=3306,user='root',password='',db='zsky',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
    currzsky = connzsky.cursor()
    taginsertsql = 'REPLACE INTO search_tags(tag) VALUES(%s)'
    currzsky.execute(taginsertsql,query)
    connzsky.commit()
    currzsky.close()
    connzsky.close()
    page=request.args.get('page',1,type=int)
    conn = pymysql.connect(host='127.0.0.1',port=9306,user='root',password='',db='film',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
    curr = conn.cursor()
    querysql='SELECT * FROM film WHERE MATCH(%s) limit %s,20'
    curr.execute(querysql,[query,(page-1)*20])
    result=curr.fetchall()
    #countsql='SELECT COUNT(*)  FROM film WHERE MATCH(%s)'
    countsql='SHOW META'
    curr.execute(countsql)
    resultcounts=curr.fetchall()
    counts=int(resultcounts[0]['Value'])
    curr.close()
    conn.close()
    pages=(counts+19)/20
    tags=Search_Tags.query.order_by(Search_Tags.id.desc()).limit(50)
    form=SearchForm()
    form.search.data=query
    return render_template('list.html',form=form,query=query,pages=pages,page=page,hashs=result,counts=counts,tags=tags)


@app.route('/main-search-kw-<query>-px-2.html',methods=['GET','POST'])
#@cache.cached(timeout=60*60,key_prefix=make_cache_key)
def search_results_bylength(query):
    connzsky = pymysql.connect(host='127.0.0.1',port=3306,user='root',password='',db='zsky',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
    currzsky = connzsky.cursor()
    taginsertsql = 'REPLACE INTO search_tags(tag) VALUES(%s)'
    currzsky.execute(taginsertsql,query)
    connzsky.commit()
    currzsky.close()
    connzsky.close()
    page=request.args.get('page',1,type=int)
    conn = pymysql.connect(host='127.0.0.1',port=9306,user='root',password='',db='film',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
    curr = conn.cursor()
    querysql='SELECT * FROM film WHERE MATCH(%s) ORDER BY length DESC limit %s,20'
    curr.execute(querysql,[query,(page-1)*20])
    result=curr.fetchall()
    #countsql='SELECT COUNT(*)  FROM film WHERE MATCH(%s)'
    countsql='SHOW META'
    curr.execute(countsql)
    resultcounts=curr.fetchall()
    counts=int(resultcounts[0]['Value'])
    curr.close()
    conn.close()
    pages=(counts+19)/20
    tags=Search_Tags.query.order_by(Search_Tags.id.desc()).limit(50)
    form=SearchForm()
    form.search.data=query
    return render_template('list_bylength.html',form=form,query=query,pages=pages,page=page,hashs=result,counts=counts,tags=tags)

@app.route('/main-show-id-<id>-dbid-0.html',methods=['GET','POST'])
#@cache.cached(timeout=60*60,key_prefix=make_cache_key)
def detail(id):
    conn = pymysql.connect(host='127.0.0.1',port=9306,user='root',password='',db='film',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
    curr = conn.cursor()
    querysql='SELECT * FROM film WHERE id=%s'
    curr.execute(querysql,int(id))
    result=curr.fetchone()
    curr.close()
    conn.close()
    #hash=Search_Hash.query.filter_by(id=id).first()
    if not result:
        return redirect(url_for('index'))        
    fenci_list=jieba.analyse.extract_tags(result['name'], 8)
    tags=Search_Tags.query.order_by(Search_Tags.id.desc()).limit(20)
    form=SearchForm()
    return render_template('detail.html',form=form,tags=tags,hash=result,fenci_list=fenci_list)


@app.route('/robots.txt')
@app.route('/sitemap.xml')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])

@app.errorhandler(404)
def notfound(e):
    return render_template("404.html"),404


class MyAdminIndexView(AdminIndexView):
    @expose('/')
    def index(self):
        connzsky = pymysql.connect(host='127.0.0.1',port=3306,user='root',password='',db='zsky',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
        currzsky = connzsky.cursor()
        totalsql = 'select count(*) from search_hash'
        currzsky.execute(totalsql)
        totalcounts=currzsky.fetchall()
        total=int(totalcounts[0]['count(*)'])
        todaysql='SELECT DAY(create_time) AS day,count(*) FROM search_hash  GROUP BY day ORDER BY day DESC limit 1'
        currzsky.execute(todaysql)
        todaycounts=currzsky.fetchall()
        today=int(todaycounts[0]['count(*)'])
        currzsky.close()
        connzsky.close()
        if not current_user.is_authenticated:
            return redirect(url_for('.login_view'))
        return self.render('admin/index.html',total=total,today=today)
    @expose('/login/', methods=('GET', 'POST'))
    def login_view(self):
        form = LoginForm(request.form)
        if helpers.validate_form_on_submit(form):
            user = form.get_user()
            if user is None:
                flash('用户名错误！')
            elif not check_password_hash(user.password, form.password.data):
                flash('密码错误！')
            elif user is not None and check_password_hash(user.password, form.password.data):
                login_user(user)
        if current_user.is_authenticated:
            return redirect(url_for('.index'))
        self._template_args['form'] = form
        #self._template_args['link'] = link
        return super(MyAdminIndexView, self).index()
    @expose('/logout/')
    def logout_view(self):
        logout_user()
        return redirect(url_for('.index'))

    
class HashView(ModelView):
    create_modal = True
    edit_modal = True
    can_export = True
    column_searchable_list = ['name']
    page=1
    def get_list(self, *args, **kwargs):
        count, data = super(HashView, self).get_list(*args, **kwargs)
        count=100
        data=Search_Hash.query.order_by(Search_Hash.id.desc()).limit(20)
        return count,data
    def is_accessible(self):
        if current_user.is_authenticated :
            return True
        return False
    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('.login_view'))


class TagsView(ModelView):
    create_modal = True
    edit_modal = True
    can_export = True
    column_searchable_list = ['tag']
    def is_accessible(self):
        if current_user.is_authenticated :
            return True
        return False
    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('.login_view'))

class UserView(ModelView):
    #column_exclude_list = 'password'
    create_modal = True
    edit_modal = True
    can_export = True
    def is_accessible(self):
        if current_user.is_authenticated :
            return True
        return False
    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('.login_view'))

admin = Admin(app,name='管理中心',index_view=MyAdminIndexView(),template_mode='bootstrap2',base_template='admin/my_master.html')
admin.add_view(HashView(Search_Hash, db.session,name='磁力Hash'))
admin.add_view(UserView(Search_Keywords, db.session,name='首页推荐'))
admin.add_view(TagsView(Search_Tags, db.session,name='搜索记录'))
admin.add_view(UserView(Search_Statusreport, db.session,name='爬取统计'))
admin.add_view(UserView(User, db.session,name='用户管理'))


@manager.command
def init_db():
    db.create_all()
    db.session.commit()


@manager.option('-u', '--name', dest='name')
@manager.option('-e', '--email', dest='email')
@manager.option('-p', '--password', dest='password')
def create_user(name,password,email):
    if name is None:
        name = raw_input('输入用户名(默认admin):') or 'admin'
    if password is None:
        password = generate_password_hash(getpass('密码:'))
    if email is None:
        email=raw_input('Email地址:')
    user = User(name=name,password=password,email=email)
    db.session.add(user)
    db.session.commit()
    print u"管理员创建成功!"

@manager.option('-np', '--newpassword', dest='newpassword')
def changepassword(newpassword):
    name = raw_input(u'输入用户名:')
    thisuser = User.query.filter_by(name=name).first()
    if not thisuser:
        print u"用户不存在,请重新输入用户名!"
        name = raw_input(u'输入用户名:')    
        thisuser = User.query.filter_by(name=name).first()
    if newpassword is None:
        newpassword = generate_password_hash(getpass(u'新密码:'))
    thisuser.password=newpassword
    db.session.add(thisuser)
    db.session.commit()
    print u"密码已更新,请牢记新密码!"

if __name__ == '__main__':
    manager.run()
