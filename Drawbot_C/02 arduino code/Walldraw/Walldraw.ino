//Wall Drawing Machine

#include <TinyStepper_28BYJ_48.h>		
#include <Servo.h>
#include <SD.h>       //SD
#include <U8x8lib.h>  //U8G2
//If there is no such lib, please press Ctrl+Shift+I to search and install from the library manager

#define STEPS_PER_TURN  (2048)  //Stepper motor turns 360 degrees in 2048 steps
#define SPOOL_DIAMETER  (35)    //Diameter of winch mm
#define SPOOL_CIRC      (SPOOL_DIAMETER * 3.1416)  //Circumference of winch 35*3.14=109.956
#define TPS             (SPOOL_CIRC / STEPS_PER_TURN)  //Step distance of stepping motor, minimum resolution, 
                                                       //the distance the rope is pulled in each step  0.053689mm

#define step_delay      1   //The waiting time of each step of the stepper motor （us）
#define TPD             300   //Waiting time when turning（ms）.

//The direction of rotation of the two motors  1 Forward   -1 Reverse  
//Adjust the in and out direction to reverse the image vertically
#define M1_REEL_OUT     -1     //Release line
#define M1_REEL_IN      1      //Involved in the line
#define M2_REEL_OUT     1      //Release line
#define M2_REEL_IN      -1     //Release line

static long laststep1, laststep2; //Current length of the line,Pen position

#define X_SEPARATION  350           //The horizontal distance above the two ropesmm 
#define LIMXMAX       ( X_SEPARATION*0.5)   //x-axis maximum  0 is in the center of the drawing board
#define LIMXMIN       (-X_SEPARATION*0.5)   //x-axis minimum

// Vertical distance parameter: The positive value is placed under the drawing board, in theory, 
//as long as the drawing board is big enough, it can be infinitely large, and the negative value 
//area is above the pen (before powering on)
#define LIMYMAX         (-250)   //y-axis maximum value at the bottom of the artboard
#define LIMYMIN         (250)    //y-axis minimum value at the top of the artboard  
//The vertical distance between the fixed point of the left and right lines and the pen should be measured 
//and placed as accurately as possible. If the error is too large, there will be distortion
//The value is reduced, the drawing becomes thinner and longer, the value is increased, the drawing 
//becomes wider and shorter


//The specific value of the angle parameter of the pen-raising servo depends on the 
//position of the swing arm and needs to be adjusted
#define PEN_UP_ANGLE    85  //Raise the pen
#define PEN_DOWN_ANGLE  70  //Write down
// =============================================

#define PEN_DOWN 1  //Pen status  Write down
#define PEN_UP 0    //Pen status  Raise the pen

U8X8_SSD1306_128X64_NONAME_HW_I2C u8x8(/* reset=*/ U8X8_PIN_NONE);   

struct point { 
  float x; 
  float y; 
  float z; 
};

struct point actuatorPos;

// plotter position 
static float posx;
static float posy;
static float posz;  // pen state
static float feed_rate = 0;

// pen state 笔状态（抬笔，落笔）.
static int ps;

/*以下为G代码通讯参数 */
#define BAUD            (115200)    //9600，57600，115200 
#define MAX_BUF         (64)      

// Serial comm reception
static int sofar;               // Serial buffer progress

static float mode_scale;   //proportion

File myFile;

Servo pen;
#define BEEP_SW 1 //Does the buzzer prompt after work?
#define BEEP A2
#define ADKEY A1
#define KEYDOWN 330
#define KEYENTER 90
#define KEYESC 517

TinyStepper_28BYJ_48 m1; //(7,8,9,10);  //M1 L Motor   in1~4 Pin UNO  7 8 9 10
TinyStepper_28BYJ_48 m2; //(2,3,5,6);  //M2 R Motor   in1~4 Pin UNO 2 3 5 6

//------------------------------------------------------------------------------

void FK(float l1, float l2,float &x,float &y) {
  float a=l1 * TPS;
  float b=X_SEPARATION;
  float c=l2 * TPS;
  
  //方法1
  float theta = acos((a*a+b*b-c*c)/(2.0*a*b));
  x = cos(theta)*l1 + LIMXMIN;
  y = sin(theta)*l1 + LIMYMIN;          

  //方法2
/*   float theta = (a*a+b*b-c*c)/(2.0*a*b);
  x = theta*l1 + LIMXMIN;
  y = sqrt (1.0 - theta * theta ) * l1 + LIMYMIN;*/
}


//------------------------------------------------------------------------------

void IK(float x,float y,long &l1, long &l2)
{
  float dy = y - LIMYMIN;
  float dx = x - LIMXMIN;
  l1 = round(sqrt(dx*dx+dy*dy) / TPS);
  dx = x - LIMXMAX;
  l2 = round(sqrt(dx*dx+dy*dy) / TPS);
}

//------------------------------------------------------------------------------

void pen_state(int pen_st)
{
  if(pen_st==PEN_DOWN)
  {
    ps=PEN_DOWN_ANGLE;
    // Serial.println("Pen down");
  } 
  else 
  {
    ps=PEN_UP_ANGLE;
    //Serial.println("Pen up");
  }
  pen.write(ps);
}

void pen_down()
{ 
  if (ps==PEN_UP_ANGLE)
  {
    ps=PEN_DOWN_ANGLE;
    pen.write(ps);
    delay(TPD);   
  }
}

void pen_up()
{
  if (ps==PEN_DOWN_ANGLE)
  {
    ps=PEN_UP_ANGLE;
    pen.write(ps);
  }  
}

//------------------------------------------------------------------------------
// returns angle of dy/dx as a value from 0...2PI
static float atan3(float dy, float dx) {
  float a = atan2(dy, dx);
  if (a < 0) a = (PI * 2.0) + a;
  return a;
}


//------------------------------------------------------------------------------

static void arc(float cx, float cy, float x, float y,  float dir) {
  // get radius
  float dx = posx - cx;
  float dy = posy - cy;
  float radius = sqrt(dx * dx + dy * dy);

  // find angle of arc (sweep)
  float angle1 = atan3(dy, dx);
  float angle2 = atan3(y - cy, x - cx);
  float theta = angle2 - angle1;

  if (dir > 0 && theta < 0) angle2 += 2 * PI;
  else if (dir < 0 && theta>0) angle1 += 2 * PI;

  // get length of arc
  // float circ=PI*2.0*radius;
  // float len=theta*circ/(PI*2.0);
  // simplifies to
  float len = abs(theta) * radius;

  int i, segments = floor(len / TPS);

  float nx, ny, nz, angle3, scale;

  for (i = 0; i < segments; ++i) {

    if (i==0) 
      pen_up();
    else
      pen_down();  
    scale = ((float)i) / ((float)segments);

    angle3 = (theta * scale) + angle1;
    nx = cx + cos(angle3) * radius;
    ny = cy + sin(angle3) * radius;
    // send it to the planner
    line_safe(nx, ny);
  }

  line_safe(x, y);
  pen_up();
}



//------------------------------------------------------------------------------
// instantly move the virtual plotter position
// does not validate if the move is valid
static void teleport(float x, float y) {
  posx = x;
  posy = y;
  long l1,l2;
  IK(posx, posy, l1, l2);
  laststep1 = l1;
  laststep2 = l2;
}


//==========================================================
//参考————斜线程序
int workcnt=0;
void moveto(float x,float y) 
{
  long l1,l2;
  IK(x,y,l1,l2);
  long d1 = l1 - laststep1;
  long d2 = l2 - laststep2;

  long ad1=abs(d1);
  long ad2=abs(d2);
  int dir1=d1>0 ? M1_REEL_IN : M1_REEL_OUT;
  int dir2=d2>0 ? M2_REEL_IN : M2_REEL_OUT;
  long over=0;
  long i;


  if(ad1>ad2) {
    for(i=0;i<ad1;++i) {
      
      m1.moveRelativeInSteps(dir1);
      over+=ad2;
      if(over>=ad1) {
        over-=ad1;
        m2.moveRelativeInSteps(dir2);
      }
      delayMicroseconds(step_delay);
     }
  } 
  else {
    for(i=0;i<ad2;++i) {
      m2.moveRelativeInSteps(dir2);
      over+=ad1;
      if(over>=ad2) {
        over-=ad2;
        m1.moveRelativeInSteps(dir1);
      }
      delayMicroseconds(step_delay);
    }
  }

  laststep1=l1;
  laststep2=l2;
  posx=x;
  posy=y;
}

//------------------------------------------------------------------------------
static void line_safe(float x,float y) {
  // split up long lines to make them straighter?
  float dx=x-posx;
  float dy=y-posy;

  float len=sqrt(dx*dx+dy*dy);
  
  if(len<=TPS) {
    moveto(x,y);
    return;
  }
  
  // too long!
  long pieces=floor(len/TPS);
  float x0=posx;
  float y0=posy;
  float a;
  for(long j=0;j<=pieces;++j) {
    a=(float)j/(float)pieces;

    moveto((x-x0)*a+x0,
         (y-y0)*a+y0);
  }
  moveto(x,y);
}


void line(float x,float y) 
{
  line_safe(x,y);
}


//********************************
void nc(String st)
{
  String xx,yy,zz;
  int ok=1;
  st.toUpperCase();
  
  float x,y,z;
  int px,py,pz;
  px = st.indexOf('X');
  py = st.indexOf('Y');
  pz = st.indexOf('Z');
  if (px==-1 || py==-1) ok=0; 
  if (pz==-1) 
  {
    pz=st.length();
  }
  else
  {   
    zz = st.substring(pz+1,st.length());
    z  = zz.toFloat();
    if (z>0)  pen_up();
    if (z<=0) pen_down();
  }

  xx = st.substring(px+1,py);
  yy = st.substring(py+1,pz);
  
  xx.trim();
  yy.trim();

  if (ok) line(xx.toFloat(),yy.toFloat()); 
}
//**********************
void working(void)
{
    u8x8.clear();
    u8x8.draw1x2String(0, 0, "Working"); 
}
//**********************
void drawfile( String filename)
{
  String rd="";
  int line=0;
  char rr=0;
  //Serial.print(F("["));
  //Serial.print(filename);
  myFile = SD.open(filename);
  if (myFile) 
  {
    //Serial.println(F("] Opened"));
    working();
    while (myFile.available()) {
    rr=myFile.read();
      
    if (rr == char(10)) 
    {
      line++;
    //          Serial.print(F("Run nc #"));
    //          Serial.print(line);
    //          Serial.println(" : "+rd);         
      nc(rd);
      rd="";
    }
    else
    {
       rd+=rr;      
    }  
    }
    myFile.close(); 
  }
  else
  {
    u8x8.clear();
    u8x8.drawString(0, 3, "Nofile");
    delay(2000);
  }
}


void setup() {
  // put your setup code here, to run once:
  Serial.begin(BAUD);
  pinMode(BEEP,OUTPUT);
  digitalWrite(BEEP,LOW);
  u8x8.begin();
  u8x8.setFont(u8x8_font_amstrad_cpc_extended_r);
  u8x8.draw1x2String(2, 3, "YZHRobot.com");

  m1.connectToPins(7,8,9,10); //M1 L Motor
  m2.connectToPins(2,3,5,6);  //M2 R Motor
  m1.setSpeedInStepsPerSecond(10000);
  m1.setAccelerationInStepsPerSecondPerSecond(100000);
  m2.setSpeedInStepsPerSecond(10000);
  m2.setAccelerationInStepsPerSecondPerSecond(100000);
  
  //抬笔舵机
  pen.attach(A0);
  ps=PEN_UP_ANGLE;
  pen.write(ps);

  //Set the current pen position to 0, 0
  teleport(0, 0);
  //scaling ratio
  mode_scale = 1;
  //Serial.println(F("Test OK!"));
  delay(1500);
  u8x8.clear();  
}

int KeyCheck(void)
{
  int value=0;
  int n = analogRead(ADKEY);
  if(n<1020)
  {
    if(n<(KEYDOWN+10))
    {
      if(n>(KEYDOWN-10))
      {
        value=1;
      }  
    }  
    if(n<(KEYENTER+10))
    {
      if(n>(KEYENTER-10))
      {
        value=2;
      }  
    } 
    if(n<(KEYESC+10))
    {
      if(n>(KEYESC-10))
      {
        value=3;
      }  
    } 
  }
  else
  {
    value=0;  
  }
  return value;
}

void beep(void)
{
  int i=5;
  m1.disableMotor();
  m2.disableMotor();
  if (!BEEP_SW) return;
  while(i--)
  {
    digitalWrite(BEEP,HIGH);   
    delay(300);    
    digitalWrite(BEEP,LOW);
    delay(300);
  }
}

void loop() {
  int keyvalue=3;
  int maincase=1;
  pen_up();
  while(true)
  {    
    if(keyvalue!=0)
    {
      while(KeyCheck());
      if(keyvalue==1)//select
      {
        //Serial.println((maincase));
        if(maincase<10)
        {
          if(maincase<3) maincase++;
          else maincase=1;
        }
        else
        {  
          if(maincase==30) maincase=31;
          //else if(maincase==31) maincase=32;
          else maincase=30;
        }
      }
      else if(keyvalue==2)//Enter
      {
        if(maincase==1)
        {
          //执行DEMO  
          working();
          demo1();
          beep();
          u8x8.clear();
        }
        else if(maincase==2)
        {
          //执行SD 
          if (!SD.begin(4)) {
            //Serial.println(F("initialization SD failed!"));
            u8x8.clear();
            u8x8.draw1x2String(0, 0, "Err");
            delay(2000);
            u8x8.clear();
          }
          else
          {            
            pen_up();
            drawfile("main.nc");
            beep();
            u8x8.clear();
          }
        }
        else if(maincase==30)
        {
          moveto(0,251);
        }
        else if(maincase==31)
        {
          moveto(0,0);
          
        }
        else
        {
          maincase*=10;
          u8x8.clear(); 
        }
      }
      else if(keyvalue==3)//ESC
      {
        if(maincase>9)
        {
          maincase/=10;
        }
        u8x8.clear();  
      }
      switch(maincase)
      {
        case 1:
        {
          u8x8.draw1x2String(0, 5, " ");
          u8x8.draw1x2String(0, 1, "- DEMO");
          u8x8.draw1x2String(2, 3, "SD");
          u8x8.draw1x2String(2, 5, "SET");
        }break;
        case 2:
        {
          u8x8.draw1x2String(0, 1, " ");
          u8x8.draw1x2String(2, 1, "DEMO");
          u8x8.draw1x2String(0, 3, "- SD");
          u8x8.draw1x2String(2, 5, "SET");
        }break;
        case 3:
        {
          u8x8.draw1x2String(0, 3, " ");
          u8x8.draw1x2String(2, 1, "DEMO");
          u8x8.draw1x2String(2, 3, "SD");
          u8x8.draw1x2String(0, 5, "- SET");
        }break;
        case 30:
        {
          u8x8.draw1x2String(0, 0, "- Top");
          u8x8.draw1x2String(0, 2, "  Zero");
        }break;
        case 31:
        {
          u8x8.draw1x2String(0, 0, "  Top");
          u8x8.draw1x2String(0, 2, "- Zero");
        }break;
        case 32:
        {
          u8x8.draw1x2String(0, 0, "  Top");
          u8x8.draw1x2String(0, 2, "  Zero");
        }break;
        default:break;  
      }
    }
    keyvalue=KeyCheck();
  }
}

//蝴蝶曲线
void butterfly_curve(int xx,int yy,int lines,int x_scale,int y_scale)
//xx,yy The center position of the butterfly, the number of lines, 
//the more complex the more x_scale, y_scale The magnification ratio of the xy axis
{
  float xa,ya,p,e;
  pen_up();
  moveto(xx,yy + y_scale  * 0.71828);
  pen_down();
  
  for(float i=0;i<6.28*lines;i+=3.14/90)
  {
          
    p=pow(sin(i/12),5);
    e=pow(2.71828,cos(i));

    xa=x_scale * sin(i) * (e - 2*cos(4*i) + p);
    ya=y_scale * cos(i) * (e - 2*cos(4*i) + p);
    line_safe(xa+xx,ya+yy); 
  }
  pen_up();
}  

//桃心曲线
void heart_curve(int xx,int yy,float x_scale,float y_scale)
//xx,yy center position of peach heart curve, x_scale, y_scale xy-axis magnification ratio
{
  float xa,ya;
  
  pen_up();
  moveto(xx,yy+y_scale * 7);
  pen_down();
  for(float i=0;i<=6.28;i+=3.14/180)
  {       
    xa=x_scale * pow(sin(i),3) * 15;
    ya=y_scale * (15*cos(i) -5*cos(2*i) - 2*cos(3*i) - cos(4*i));
    line_safe(xa+xx,ya+yy);  
  }
  pen_up();
} 

//box1
void rectangle(float xx,float yy,float dx,float dy,float angle)
{
  float six,csx,siy,csy;
  dx/=2;
  dy/=2;

  six = sin(angle/180*3.14) * dx;
  csx = cos(angle/180*3.14) * dx;
  
  siy = sin(angle/180*3.14) * dy;
  csy = cos(angle/180*3.14) * dy;
  
  pen_up();
  line_safe(csx - siy + xx,six + csy + yy);
  pen_down();
  line_safe(xx - csx - siy,csy - six + yy);
  line_safe(xx - csx + siy,yy - csy - six);
  line_safe(csx + siy + xx,six - csy + yy);
  line_safe(csx - siy + xx,six + csy + yy);
  pen_up();
}

//box2
void box(float xx,float yy,float dx,float dy)
  {
  pen_up();
  line_safe(xx , yy);
  pen_down();
  delay(TPD);
  line_safe(xx + dx, yy);
  delay(TPD);
  line_safe(xx + dx, yy+ dy);
  delay(TPD);
  line_safe(xx , yy + dy);
  delay(TPD);
  line_safe(xx , yy);
  pen_up();

}


void circle(float xx,float yy,float radius_x,float radius_y)
{
  float rx,ry;
  float st= 3.14159 / 90; //Circle division accuracy
  pen_up();
  line(xx+radius_x,yy);
  pen_down();
  for(float i=0;i<6.28318;i+=st)
  {
    rx = cos(i) * radius_x;
    ry = sin(i) * radius_y;
    line(xx+rx,yy+ry);
  }
  pen_up();
}


void demo1()
{
  pen_up();
  box(-45,0,90,90);
  moveto(-15,0);
  pen_down();
  line(-15,90);
  pen_up();
  moveto(15,90); 
  pen_down();
  line(15,0);
  pen_up();
  moveto(-45,30); 
  pen_down();
  line(45,30);
  pen_up();
  moveto(45,60); 
  pen_down();
  line(-45,60);
  pen_up();
  
  box(-42.5,62.5,25,25);
  circle(0,75,12.5,12.5);
  rectangle(30,75,17.7,17.7,45);
  
  rectangle(-30,45,17.7,17.7,45);
  box(-12.5,32.5,25,25);
  circle(30,45,12.5,12.5);
  
  circle(-30,15,12.5,12.5);
  rectangle(0,15,17.7,17.7,45);
  box(17.5,2.5,25,25);

  heart_curve(-45,-45,2,2);

  butterfly_curve(45,-55,3,12,12);
}
