import os
import uuid
import logging
import jinja2
import webapp2

from datetime import datetime, timedelta
from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.api import mail
from google.appengine.api import images

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

class Resource(ndb.Model):    
    id = ndb.StringProperty(indexed=True, required=True)
    resourceName = ndb.StringProperty(indexed=True)
    ownerID = ndb.StringProperty(indexed=True)
    availableStartTime = ndb.StringProperty(indexed=False)
    availableEndTime = ndb.StringProperty(indexed=False)
    tags = ndb.StringProperty(repeated=True)
    numberOfTimesReserved = ndb.IntegerProperty(indexed=False, default=0)
    lastReservationTime = ndb.DateTimeProperty(auto_now_add=False)
    capacity = ndb.IntegerProperty(indexed=False, default=1)
    avatar = ndb.BlobProperty()
    description = ndb.StringProperty(indexed=False)    
    
class Reservation(ndb.Model):    
    reservationID = ndb.StringProperty(indexed=True, required=True)
    resourceID = ndb.StringProperty(indexed=True, required=True)
    date = ndb.DateProperty(indexed=True)
    ownerID = ndb.StringProperty(indexed=True)
    startTime = ndb.StringProperty(indexed=True)
    endTime = ndb.StringProperty(indexed=False)
    resourceName = ndb.StringProperty(indexed=False)
    duration = ndb.StringProperty(indexed=False)
    ownerEmail = ndb.StringProperty(indexed=False)
    
def getResourceByResourceID(resourceID):
    """ Returns the resource having the requested ID """
    return Resource.query(Resource.id == resourceID).fetch()[0]

def getAllResources():
    """ Returns all resources ordered by the last reservation time in reverse """
    return Resource.query().order(-Resource.lastReservationTime).fetch()

def getUserResourcesByUserID(userID):
    """ Returns all resources owned by the requested userID"""
    return Resource.query(Resource.ownerID == str(userID)).order(-Resource.lastReservationTime).fetch()

def getReservationsByResourceID(resourceID):
    """ Returns all reservations made for the resource with the requested resourceID, sorted by reservation date and time"""
    resourceReservations = Reservation.query(Reservation.resourceID == resourceID).order(Reservation.date, Reservation.startTime).fetch()
    return collectUpcomingReservationsOnly(resourceReservations)

def getReservationsByUserID(userID):
    """ Returns all reservations made by the user with the requested userID, sorted by reservation date and time """
    userReservations = Reservation.query(Reservation.ownerID == str(userID)).order(Reservation.date, Reservation.startTime).fetch()
    return collectUpcomingReservationsOnly(userReservations)
    
def collectUpcomingReservationsOnly(reservations):    
    """ Returns reservations whose end time has not yet passed """
    upcomingReservations=[]
    for reservation in reservations:
        if not hasReservationTimePassed(str(reservation.date), reservation.endTime):
            upcomingReservations.append(reservation)
    return upcomingReservations

def formatOnlyDate(requestedDate):
    """ Converts string value of date to DateTime """
    return datetime.strptime(requestedDate , '%Y-%m-%d')

def formatToDateTime(stringDate, stringTime):
    """ Converts string value of date and time to DateTime """
    requestedDateTime = stringDate + " " + stringTime
    return datetime.strptime(requestedDateTime, '%Y-%m-%d %H:%M')

def sendReservationStartedEmail(reservation):
    """ Initiates action to send resource reminder email upon start of a reservation """
    mail.send_mail(sender="anishabhatla281@gmail.com", to=reservation.ownerEmail, subject="Reservation Started Notification", 
                   body="""This is to notify you that your booking of resource: """ + reservation.resourceName + """ for date: """ 
                   + str(reservation.date) + """ from """ + reservation.startTime + """ hours for duration: """ + 
                   reservation.duration + """ has now started!""")
    
def calculateRequestedTimeArray(requestedTime):
    """ Splits string value of time to hours and minutes """
    timeArray = requestedTime.split(":")            
    if timeArray[0] < 10:
        timeArray[0] = timeArray[0]%10    
    if timeArray[1] < 10:
        timeArray[1] = timeArray[1]%10        
    return timeArray   
   
def calculateEndTimeArray(startTimeArray, durationArray):
    """ Calculates end time of a reservation from its start time and duration"""   
    endTimeTotalInMinutes = int(startTimeArray[0])*60 + int(startTimeArray[1]) + int(durationArray[0])*60 + int(durationArray[1]);
    requestedEndTimeHours = endTimeTotalInMinutes/60;
    requestedEndTimeMinutes = endTimeTotalInMinutes%60;
    endTimeArray = str(requestedEndTimeHours) + ":" + str(requestedEndTimeMinutes)
    return endTimeArray

def hasReservationTimePassed(requestedDate, requestedTime):
    """ Checks if the requested reservation time is before the current time. Since the seconds field
    is not taken into consideration, if the current time is 12:17 PM, a requested time of 12:17 PM will be
    considered as passed for the current date. """  
    currentDateTime = datetime.now() - timedelta(hours = 4)
    requestedDateFormatted = formatOnlyDate(requestedDate)
    if requestedDateFormatted.date() < currentDateTime.date():
        return True
    elif requestedDateFormatted.date() == currentDateTime.date():
        requestedDateTimeFormatted = formatToDateTime(requestedDate, requestedTime)
        if requestedDateTimeFormatted < currentDateTime:
            return True
        return False
    return False
    
def hasResourceReachedCapacity(resourceID, requestedDate, requestedStartTime, endTimeArray, capacity):
    """ Checks if the resource has reached capacity of reservations allowed to exist at the same time """  
    currentResourceReservations = getReservationsByResourceID(resourceID)
    requestedDateStartTimeFormatted = formatToDateTime(requestedDate, requestedStartTime)
    requestedDateEndTimeFormatted = formatToDateTime(requestedDate, endTimeArray)
    
    overlappingReservations = 0
    requestedDateFormatted = formatOnlyDate(requestedDate)
    
    for reservation in currentResourceReservations:
        if reservation.date == requestedDateFormatted.date():
            reservationDateStartTimeFormatted = formatToDateTime(str(reservation.date), reservation.startTime)
            reservationDateEndTimeFormatted = formatToDateTime(str(reservation.date), reservation.endTime)
            
            if reservationDateStartTimeFormatted == requestedDateStartTimeFormatted:
                overlappingReservations +=1
            elif reservationDateStartTimeFormatted < requestedDateStartTimeFormatted:
                if reservationDateEndTimeFormatted > requestedDateStartTimeFormatted:
                    overlappingReservations +=1
            elif reservationDateStartTimeFormatted > requestedDateStartTimeFormatted:
                if reservationDateStartTimeFormatted < requestedDateEndTimeFormatted:
                    overlappingReservations +=1
        
    if overlappingReservations == capacity:
        return True
    else:
        return False

def checkClashWithOtherReservationsOfUser(requestedDate, requestedStartTime, endTimeArray, user):
    """ Checks if the reservation time requested by the user overlaps with another reservation already made by the same user """  
    userReservations = getReservationsByUserID(user.user_id())
    requestedDateStartTimeFormatted = formatToDateTime(requestedDate, requestedStartTime)
    requestedDateEndTimeFormatted = formatToDateTime(requestedDate, endTimeArray)    
    requestedDateFormatted = formatOnlyDate(requestedDate)
    
    for reservation in userReservations:
        if reservation.date == requestedDateFormatted.date():
            reservationDateStartTimeFormatted = formatToDateTime(str(reservation.date), reservation.startTime)
            reservationDateEndTimeFormatted = formatToDateTime(str(reservation.date), reservation.endTime)
            
            if reservationDateStartTimeFormatted == requestedDateStartTimeFormatted:
                return True
            elif reservationDateStartTimeFormatted < requestedDateStartTimeFormatted:
                if reservationDateEndTimeFormatted > requestedDateStartTimeFormatted:
                    return True
            elif reservationDateStartTimeFormatted > requestedDateStartTimeFormatted:
                if reservationDateStartTimeFormatted < requestedDateEndTimeFormatted:
                    return True
        
    return False

class LandingPage(webapp2.RequestHandler):
    
    def get(self):
        """ Generates the home page of the application """
        user = users.get_current_user()
        if user:      
            allResources = getAllResources()
            userResources = getUserResourcesByUserID(user.user_id())
            userReservations = getReservationsByUserID(user.user_id())
            url = users.create_logout_url(self.request.uri)
            template_values = {               
                'user': user,
                'allResources': allResources,
                'userResources': userResources,
                'userReservations': userReservations,
                'url': url,               
                'displayAllSections': True,
                'width':14          
            }
            template = JINJA_ENVIRONMENT.get_template('index.html')
            self.response.write(template.render(template_values))
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
    
class UserPage(webapp2.RequestHandler):
    
        def get(self):
            """ Generates page to view all upcoming reservations of a particular user 
            and resources owned by that particular user """
            user = users.get_current_user()
            if user:
                ownerID = self.request.get('value')
                userResources = getUserResourcesByUserID(ownerID)
                userReservations = getReservationsByUserID(ownerID)
                for reservation in userReservations:
                    ownerEmail = reservation.ownerEmail
                    break
                url = users.create_logout_url(self.request.uri)
                template_values = {
                    'user': ownerEmail,
                    'userResources': userResources,
                    'userReservations': userReservations,
                    'url': url,
                    'displayAllSections': False,
                    'width':25              
                }
                template = JINJA_ENVIRONMENT.get_template('index.html')
                self.response.write(template.render(template_values))
            
            else:
                url = users.create_login_url(self.request.uri)
                self.redirect(url)
                
class CreateResource(webapp2.RequestHandler):
    
    def get(self):
        """ Generates the page to create a new resource """
        user = users.get_current_user()
        if user:
            url = users.create_logout_url(self.request.uri)
            template_values={
                'url': url
            }
            template = JINJA_ENVIRONMENT.get_template('createResource.html')
            self.response.write(template.render(template_values))
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
    
    def post(self):
        """ Adds the new resource to GAE's datastore """
        user = users.get_current_user()
        if user:
            resourceName = self.request.get('resourceName').strip()
            availableStartTime = self.request.get('availableStartTime')
            availableEndTime = self.request.get('availableEndTime')
            tags = self.request.get('tags').strip()
            capacity = self.request.get('capacity')
            description = self.request.get('description').strip()
            avatar = self.request.get('img')
            
            tempTagsArray = tags.split(",");
            tagsSet=set()
            for tag in tempTagsArray:
                tagsSet.add(tag.strip())
            
            resource = Resource()
            resource.id = str(uuid.uuid4())
            resource.resourceName = resourceName
            resource.ownerID = str(users.get_current_user().user_id())
            resource.availableStartTime = availableStartTime
            resource.availableEndTime = availableEndTime
            resource.tags = tagsSet
            resource.capacity = int(capacity)
            if description and description.strip():
                    resource.description = description.strip()
            if avatar:
                avatar = images.resize(avatar, 32, 32)
                resource.avatar = avatar
            
            resource.put()
            url = users.create_logout_url(self.request.uri)
            template_values = {
                'resource': resource,
                'enableEditingResource': True,
                'url': url,
                'printSuccessMessage': True,
            }
            template = JINJA_ENVIRONMENT.get_template('createResource.html')
            self.response.write(template.render(template_values))   
        
class ResourcePage(webapp2.RequestHandler):
    
    def get(self):
        """ Generates page to view details of a resource """     
        user = users.get_current_user()        
        if user:            
            rid = self.request.get('value')
            resource = getResourceByResourceID(rid)
            
            if resource.ownerID == str(user.user_id()):
                enableEditing = True
                navigationBarWidth = 20
            else:
                enableEditing = False
                navigationBarWidth = 25 
            
            url = users.create_logout_url(self.request.uri)
            
            template_values = {
                'resource': resource,
                'enableEditingResource': enableEditing,
                'width': navigationBarWidth,
                'url': url
            }
            template = JINJA_ENVIRONMENT.get_template('resourcePage.html')
            self.response.write(template.render(template_values))
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
            
class EditResource(webapp2.RequestHandler):
    
    def get(self):
        """ Generates page to edit an already existing resource """
        user = users.get_current_user()
        if user:
            rid = self.request.get('value')
            resource = getResourceByResourceID(rid)
            tagsString = ','.join(resource.tags)
            url = users.create_logout_url(self.request.uri)            
            template_values = {
                'resource': resource,
                'tags': tagsString,
                'url': url
            }
            template = JINJA_ENVIRONMENT.get_template('editResource.html')
            self.response.write(template.render(template_values))
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
            
    def post(self):
        """ Makes changes to an already existing resource as per user input """
        user = users.get_current_user()
        if user:
            rid = self.request.get('resourceID')
            resourceName = self.request.get('resourceName').strip()
            availableStartTime = self.request.get('availableStartTime')
            availableEndTime = self.request.get('availableEndTime')
            tags = self.request.get('tags').strip()
            capacity = self.request.get('capacity')
            description = self.request.get('description').strip()
            avatar = self.request.get('img')
            
            tempTagsArray = tags.split(",");
            tagsSet=set()
            for tag in tempTagsArray:
                tagsSet.add(tag.strip())
            
            resource = getResourceByResourceID(rid)
            resource.resourceName = resourceName
            resource.availableStartTime = availableStartTime
            resource.availableEndTime = availableEndTime
            resource.tags = tagsSet
            resource.capacity = int(capacity)
            if description and description.strip():
                    resource.description = description.strip()
            else:
                resource.description = None
            if avatar:
                avatar = images.resize(avatar, 32, 32)
                resource.avatar = avatar
                
            resource.put()
            
            message = resource.resourceName + " has been edited."
            allResources = getAllResources()
            userResources = getUserResourcesByUserID(user.user_id())
            userReservations = getReservationsByUserID(user.user_id())
            
            url = users.create_logout_url(self.request.uri)
            template_values = {
                'user': user,
                'allResources': allResources,
                'userResources': userResources,
                'userReservations': userReservations,
                'url': url,
                'displayAllSections': True,
                'width':14,
                'message': message      
            }
            template = JINJA_ENVIRONMENT.get_template('index.html')
            self.response.write(template.render(template_values))        
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
            
class CreateReservation(webapp2.RequestHandler):
    
    def get(self):
        """ Generates page to add a new reservation for a resource """
        user = users.get_current_user()
        if user:
            rid = self.request.get('value')
            resource = getResourceByResourceID(rid)
            url = users.create_logout_url(self.request.uri)
            
            template_values = {
                'resource': resource,
                'url': url   
            }
            template = JINJA_ENVIRONMENT.get_template('createReservation.html')
            self.response.write(template.render(template_values))
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
            
    def post(self):
        """ Adds a new reservation to GAE's datastore after validating the user inputted values: 
        the requested start time should not be before or equal to the current time, the resource should 
        not have reached capacity for the requested time and the user should not have any 
        overlapping reservations for the requested time """
        user = users.get_current_user()
        if user:
            rid = self.request.get('resourceID')
            requestedDate = self.request.get('reservationDate')
            requestedStartTime = self.request.get('startTime')
            requestedDuration = self.request.get('duration')
            resource = getResourceByResourceID(rid)
            url = users.create_logout_url(self.request.uri)
            
            if hasReservationTimePassed(requestedDate, requestedStartTime):
                template_values = {
                'resource': resource,
                'message': "The requested start time has already elapsed!" ,
                'url': url
                }
                template = JINJA_ENVIRONMENT.get_template('createReservation.html')
                self.response.write(template.render(template_values))
            
            else:
                startTimeArray = calculateRequestedTimeArray(requestedStartTime)
                durationArray = calculateRequestedTimeArray(requestedDuration)
                endTimeArray = calculateEndTimeArray(startTimeArray, durationArray)   
                if hasResourceReachedCapacity(rid, requestedDate, requestedStartTime, endTimeArray, resource.capacity):
                        errorMessage = resource.resourceName + " has reached capacity for the requested time!"
                        template_values = {
                        'resource': resource,
                        'message': errorMessage,
                        'url': url
                        }
                        template = JINJA_ENVIRONMENT.get_template('createReservation.html')
                        self.response.write(template.render(template_values))
                
                else:            
                    if checkClashWithOtherReservationsOfUser(requestedDate, requestedStartTime, endTimeArray, user):
                        template_values = {
                        'resource': resource,
                        'url': url,
                        'message': "You already have a reservation at the requested time. No overlapping reservations allowed!"  
                        }
                        template = JINJA_ENVIRONMENT.get_template('createReservation.html')
                        self.response.write(template.render(template_values))
                    else:
                        reservation = Reservation()
                        reservation.reservationID = str(uuid.uuid4())
                        reservation.date = formatOnlyDate(requestedDate).date()
                        reservation.startTime = ':'.join(startTimeArray)
                        reservation.endTime = endTimeArray
                        reservation.duration = ':'.join(durationArray)
                        reservation.resourceID = rid
                        reservation.resourceName = resource.resourceName
                        reservation.ownerEmail = str(user.email())
                        reservation.ownerID = str(user.user_id())
                        reservation.put()
                        resource.lastReservationTime = datetime.now()
                        resource.numberOfTimesReserved += 1
                        resource.put()
                        
                        message="The reservation has been made."
                        template_values = {
                            'resource': resource,
                            'url': url,
                            'enableEditingResource': True,
                            'width': 20,
                            'message': message
                        }
                        template = JINJA_ENVIRONMENT.get_template('resourcePage.html')
                        self.response.write(template.render(template_values))   
               
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)

class ViewReservations(webapp2.RequestHandler):
    
    def get(self):
        """ Generates page to view all upcoming reservations for a resource """
        user = users.get_current_user()
        if user:
            rid = self.request.get('value')
            resource = getResourceByResourceID(rid)
            resourceReservations = getReservationsByResourceID(rid)
            url = users.create_logout_url(self.request.uri)
            
            template_values = {
                'resource': resource,
                'reservations': resourceReservations,
                'url': url
            }
            template = JINJA_ENVIRONMENT.get_template('viewReservations.html')
            self.response.write(template.render(template_values))
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
   
class DeleteReservation(webapp2.RequestHandler): 
    
    def get(self):
        """ Deletes an already existing reservation """
        user = users.get_current_user()
        if user:
            reservationID = self.request.get('value')
            reservations = Reservation.query(Reservation.reservationID == reservationID).fetch()
            for reservation in reservations:
                reservation.key.delete()
                
            allResources = getAllResources()
            userResources = getUserResourcesByUserID(user.user_id())
            userReservations = getReservationsByUserID(user.user_id())
            
            url = users.create_logout_url(self.request.uri)
            template_values = {
                'user': user,
                'allResources': allResources,
                'userResources': userResources,
                'userReservations': userReservations,
                'url': url,
                'displayAllSections': True,
                'width':14          
            }
            template = JINJA_ENVIRONMENT.get_template('index.html')
            self.response.write(template.render(template_values))           
        
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
            
class TagPage(webapp2.RequestHandler):
    
    def get(self):
        """ Generates page to view all resources that are tagged by a particular tag """
        user = users.get_current_user()
        if user:
            tag = self.request.get('value')
            tag = tag.strip()
            allResources = Resource.query().fetch()
            resources=[]
            for resource in allResources:
                if tag in resource.tags:
                    resources.append(resource)
            
            url = users.create_logout_url(self.request.uri)
            
            template_values = {
                'tag': tag,
                'resources': resources,
                'url': url
            }
            template = JINJA_ENVIRONMENT.get_template('tagPage.html')
            self.response.write(template.render(template_values))
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)    
   
class RSSPage(webapp2.RequestHandler):
    
    def get(self):
        """ Generates RSS which displays all upcoming and past/undeleted reservations for an existing resource in an XML format """
        user = users.get_current_user()
        if user:
            rid = self.request.get('value')
            resource = getResourceByResourceID(rid)
            resourceReservations = getReservationsByResourceID(rid)
            resourceReservations = Reservation.query(Reservation.resourceID == rid).order(Reservation.date, Reservation.startTime).fetch()
            url = users.create_logout_url(self.request.uri)
            
            template_values = {
                'resourceName': resource.resourceName,
                'reservations': resourceReservations,
                'url': url
            }
            template = JINJA_ENVIRONMENT.get_template('RSSPage.html')
            self.response.write(template.render(template_values))
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)    
        
class SearchName(webapp2.RequestHandler):
    
    def get(self):
        """ Generates page to display resource details of resources with a particular case-sensitive name """
        user = users.get_current_user()
        if user:
            nameToBeSearched = self.request.get('resourceName').strip()
            resources = Resource.query(Resource.resourceName == nameToBeSearched).fetch()
            url = users.create_logout_url(self.request.uri)
            
            template_values = {
                'resources': resources,
                'url': url           
            }
            template = JINJA_ENVIRONMENT.get_template('searchResults.html')
            self.response.write(template.render(template_values))            
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)    

class SendMailViaCron(webapp2.RequestHandler):    
    
    def get(self):
        """ Sends a reminder email to the user, who booked the reservation, when the reservation starts """
        logging.info("In sendmailviacron function!")
        reservations = Reservation.query().fetch()
        reservations = collectUpcomingReservationsOnly(reservations)
        for reservation in reservations:        
            currentDateTime = datetime.now() - timedelta(hours = 4)
            requestedDateTimeFormatted = formatToDateTime(str(reservation.date), reservation.startTime)
            if (requestedDateTimeFormatted.date() == currentDateTime.date()) and (requestedDateTimeFormatted.hour == currentDateTime.hour) and (requestedDateTimeFormatted.minute == currentDateTime.minute):
                logging.info("Sending mail in sendmailviacron!!!")
                try:  
                    sendReservationStartedEmail(reservation)
                except:
                    logging.exception('')
        logging.info("Leaving sendmailviacron function!")

class GetImage(webapp2.RequestHandler):
    
    def get(self):
        """ Returns the image associated with a resource, if any """
        user = users.get_current_user()
        if user:
            rid = self.request.get('value')
            resource = getResourceByResourceID(rid)
            self.response.headers['Content-Type'] = 'image/png'
            self.response.out.write(resource.avatar)
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
     
class SearchByAvailability(webapp2.RequestHandler):
    
    def get(self):
        """ Generates page to search for resources that are available for booking at a particular date, time and duration """
        user = users.get_current_user()
        if user:
            url = users.create_logout_url(self.request.uri)
            template_values = {
                'url': url,                
                'width':14          
            }
            template = JINJA_ENVIRONMENT.get_template('searchByAvailability.html')
            self.response.write(template.render(template_values))
            
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
    
    def post(self):
        """ Returns a list of resources that are available at the requested time, if any,
        after validating the user inputted values like: the requested start time should not 
        be before or equal to the current time and the resource should not have reached capacity 
        for the requested time """
        user = users.get_current_user()
        if user:
            requestedDate = self.request.get('reservationDate')
            requestedStartTime = self.request.get('startTime')
            requestedDuration = self.request.get('duration')
            url = users.create_logout_url(self.request.uri)
            
            if hasReservationTimePassed(requestedDate, requestedStartTime):
                template_values = {
                'message': "The requested start time has already elapsed!",
                'url': url 
                }
                template = JINJA_ENVIRONMENT.get_template('searchByAvailability.html')
                self.response.write(template.render(template_values))
            
            else:
                listOfAvailableResources=[]
                startTimeArray = calculateRequestedTimeArray(requestedStartTime)
                durationArray = calculateRequestedTimeArray(requestedDuration)
                endTimeArray = calculateEndTimeArray(startTimeArray, durationArray)
                endTimeInMinutes = int(startTimeArray[0])*60 + int(startTimeArray[1]) + int(durationArray[0])*60 + int(durationArray[1]);
                allResources = Resource.query().fetch()
                
                for resource in allResources:
                    availableStartTimeArray = resource.availableStartTime.split(":")
                    availableEndTimeArray = resource.availableEndTime.split(":")
                    availableEndTimeInMinutes = int(availableEndTimeArray[0])*60 + int(availableEndTimeArray[1])
                    if startTimeArray[0] < availableStartTimeArray[0]:
                        continue
                    elif (startTimeArray[0] == availableStartTimeArray[0]) and (startTimeArray[1] < availableStartTimeArray[1]):
                        continue
                    if endTimeInMinutes > availableEndTimeInMinutes:
                        continue
                    else:
                        rid = resource.id                
                        if hasResourceReachedCapacity(rid, requestedDate, requestedStartTime, endTimeArray, resource.capacity):
                                continue                        
                        else:
                            listOfAvailableResources.append(resource)
                
                template_values = {
                    'resources': listOfAvailableResources,
                    'url': url           
                }
                template = JINJA_ENVIRONMENT.get_template('searchResults.html')
                self.response.write(template.render(template_values))   
               
        else:
            url = users.create_login_url(self.request.uri)
            self.redirect(url)
               
application = webapp2.WSGIApplication([
    ('/', LandingPage),
    ('/userPage', UserPage),
    ('/createResource', CreateResource),
    ('/resourcePage', ResourcePage),
    ('/editResource', EditResource),
    ('/createReservation', CreateReservation),
    ('/viewReservations',ViewReservations),
    ('/deleteReservation', DeleteReservation),  
    ('/tagPage', TagPage),
    ('/rssPage', RSSPage),
    ('/searchName', SearchName),
    ('/sendMailViaCron', SendMailViaCron),
    ('/getImage', GetImage),
    ('/searchByAvailability', SearchByAvailability)   
], debug=True)