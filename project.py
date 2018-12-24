#!/usr/bin/python2
from flask import Flask, render_template, request
from flask import redirect, jsonify, url_for, flash
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Brand, Item, User
from flask import session as login_session
import random
import string
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Sport Tools Application"


# Connect to Database and create database session
engine = create_engine('sqlite:///brandmenuApp.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(
        random.choice(
            string.ascii_uppercase + string.digits) for x in range(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code, now compatible with Python3
    # request.get_data()
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    # Submit request, parse response - Python3 compatible
    h = httplib2.Http()
    response = h.request(url, 'GET')[1]
    str_response = response.decode('utf-8')
    result = json.loads(str_response)

    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ''' style = "width: 300px;
    height: 300px;
    border-radius: 150px;
    -webkit-border-radius: 150px;
    -moz-border-radius: 150px;"> '''
    flash("you are now logged in as %s" % login_session['username'])
    return output

# User Helper Functions


def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).first()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except Nothing:
        return None

# DISCONNECT - Revoke a current user's token and reset their login_session


@app.route('/gdisconnect')
def gdisconnect():
        # Only disconnect a connected user.
    access_token = login_session.get('access_token')
    if access_token is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] == '200':
        # Reset the user's sesson.
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']

        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        # For whatever reason, the given token was invalid.
        response = make_response(
            json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# JSON APIs to view Brands Information
@app.route('/brand/<int:brand_id>/item/JSON')
def BrandMenuJSON(brand_id):
    brand = session.query(Brand).filter_by(id=brand_id).one()
    items = session.query(Item).filter_by(
        brand_id=brand_id).all()
    return jsonify(Items=[i.serialize for i in items])


@app.route('/brand/JSON')
def brandJSON():
    brands = session.query(Brand).all()
    return jsonify(brands=[r.serialize for r in brands])


# Show all Brands
@app.route('/')
@app.route('/brand/')
def showBrands():
    brands = session.query(Brand).order_by(asc(Brand.name))
    # if 'username' not in login_session:
    #     return render_template('publicBrands.html', brands=brands)
    # else:
    return render_template('brands.html', brands=brands)


# Create a new Brand
@app.route('/brands/new/', methods=['GET', 'POST'])
def newBrand():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        NewBrand = Brand(
            name=request.form['name'],
            user_id=login_session['user_id'])
        session.add(NewBrand)
        flash('New Brand %s Successfully Created' % NewBrand.name)
        session.commit()
        return redirect(url_for('showBrands'))
    else:
        return render_template('newBrand.html')


# Edit a Brand
@app.route('/brand/<int:brand_id>/edit/', methods=['GET', 'POST'])
def editBrand(brand_id):
    editedBrand = session.query(
        Brand).filter_by(id=brand_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if editedBrand.user_id != login_session['user_id']:
        return '''<script>function myFunction() {
            alert('You are not authorized to edit this Brand.
            Please create your own Brand in order to edit.');}
            </script><body onload='myFunction()''>'''
    if request.method == 'POST':
        if request.form['name']:
            editedBrand.name = request.form['name']
        flash('Brand Successfully Edited %s' % editedBrand.name)
        return redirect(url_for('showBrands'))
    else:
        return render_template('editBrand.html', brand=editedBrand)


# Delete a Brand
@app.route('/brand/<int:brand_id>/delete/', methods=['GET', 'POST'])
def deleteBrand(brand_id):
    deletedBrand = session.query(
        Brand).filter_by(id=brand_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if deletedBrand.user_id != login_session['user_id']:
        return '''<script>function myFunction() {
            alert('You are not authorized to delete this Brand.');}
            </script><body onload='myFunction()''>'''
    if request.method == 'POST':
        session.delete(deletedBrand)
        flash('%s Successfully Deleted' % deletedBrand.name)
        session.commit()
        return redirect(url_for('showBrands', brand_id=brand_id))
    else:
        return render_template('deleteBrand.html', brand=deletedBrand)


# Show all Items
@app.route('/brand/<int:brand_id>/')
@app.route('/brand/<int:brand_id>/item')
def showItems(brand_id):
    brand = session.query(Brand).filter_by(id=brand_id).one()
    creator = getUserInfo(brand.user_id)
    items = session.query(Item).filter_by(
        brand_id=brand_id).all()
    if 'username' not in login_session or creator.id != login_session[
         'user_id']:
        return render_template(
            'publicItems.html', items=items, brand=brand, creator=creator)
    else:
        return render_template(
            'showItems.html', items=items, brand=brand, creator=creator)


# Create a new item
@app.route('/brand/<int:brand_id>/item/new', methods=['GET', 'POST'])
def newItem(brand_id):
    if 'username' not in login_session:
        return redirect('/login')
    brand = session.query(Brand).filter_by(id=brand_id).one()
    if login_session['user_id'] != brand.user_id:
            return '''<script>function myFunction() {
                alert('You are not authorized to add items.
                Please create your own Brand
                in order to make and item.');}
                </script><body onload='myFunction()''>'''
    brand = session.query(Brand).filter_by(id=brand_id).one()
    if request.method == 'POST':
        newItem = Item(name=request.form['name'],
                       description=request.form['description'],
                       price=request.form['price'],
                       brand_id=brand_id, user_id=brand.user_id)
        session.add(newItem)
        session.commit()
        flash('New Item named %s Successfully Created' % (newItem.name))
        return redirect(url_for('showItems', brand_id=brand_id))
    else:
        return render_template('newItem.html', brand_id=brand_id)


# Edit an item
@app.route(
    '/brand/<int:brand_id>/item/<int:item_id>/edit/', methods=['GET', 'POST'])
def editItem(brand_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')
    editedItem = session.query(Item).filter_by(id=item_id).one()
    brand = session.query(Brand).filter_by(id=brand_id).one()
    if login_session['user_id'] != brand.user_id:
        return '''<script>function myFunction() {alert('You are not authorized
                to edit Items of this brand. Please create your own brand
                first.');}</script><body
                onload='myFunction()''>'''
    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        if request.form['price']:
            editedItem.price = request.form['price']
        session.add(editedItem)
        session.commit()
        flash('Item Successfully Edited')
        return redirect(url_for('showItems', brand_id=brand_id))
    else:
        return render_template(
            'editItem.html', brand_id=brand_id,
            item_id=item_id, item=editedItem)


# Delete an item
@app.route('/brand/<int:brand_id>/item/<int:item_id>/delete',
           methods=['GET', 'POST'])
def deleteItem(brand_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')
    brand = session.query(Brand).filter_by(id=brand_id).one()
    deletedItem = session.query(Item).filter_by(id=item_id).one()
    if login_session['user_id'] != brand.user_id:
        return '''<script>function myFunction() {alert('You are not authorized
                to delete items of this brand. Please create your own
                brand first.');}</script><body
                onload='myFunction()''>'''
    if request.method == 'POST':
        session.delete(deletedItem)
        session.commit()
        flash('Item Successfully Deleted')
        return redirect(url_for('showItems', brand_id=brand_id))
    else:
        return render_template('deleteItem.html', item=deletedItem)


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
