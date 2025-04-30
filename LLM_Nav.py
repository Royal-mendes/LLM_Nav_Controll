#!/usr/bin/env python3
import rospy
import os
import requests
import json
import threading
from nav_msgs.msg import NavGoal

class ErnieNavCommander:
    def __init__(self):
        rospy.init_node('ernie_nav_commander', log_level=rospy.DEBUG)
        
        # ROS发布器
        self.nav_pub = rospy.Publisher('/nav_commands', NavGoal, queue_size=10)
        
        # 验证环境变量
        self.api_key = os.getenv("BAIDU_API_KEY")
        self.secret_key = os.getenv("BAIDU_SECRET_KEY")
        if not self.api_key or not self.secret_key:
            rospy.logfatal("未找到API密钥！请执行：")
            rospy.logfatal("export BAIDU_API_KEY='你的API_KEY'")
            rospy.logfatal("export BAIDU_SECRET_KEY='你的SECRET_KEY'")
            rospy.signal_shutdown("缺少API密钥")
            return
        
        # 预设导航点
        self.nav_points = {
            "A点": {"x": 1.5, "y": 0.8, "theta": 90},
            "B点": {"x": 2.3, "y": -1.2, "theta": 45},
            "充电桩": {"x": 0.0, "y": 0.0, "theta": 180}
        }
        
        # 输入处理线程
        self.running = True
        self.input_thread = threading.Thread(target=self.process_input)
        self.input_thread.start()
        
        rospy.on_shutdown(self.cleanup)
        rospy.loginfo("ERNIE导航指令节点已启动")

    def get_access_token(self):
        """获取API访问令牌"""
        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key
        }
        try:
            resp = requests.post(url, params=params, timeout=5)
            if resp.status_code != 200:
                rospy.logerr(f"Token获取失败 HTTP {resp.status_code}")
                return None
            return resp.json().get("access_token")
        except Exception as e:
            rospy.logerr(f"获取Token异常: {str(e)}")
            return None

    def parse_command(self, text):
        """符合百度API规范的指令解析"""
        token = self.get_access_token()
        if not token:
            return None
            
        api_url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token={token}"
        
        # 将系统提示合并到用户输入
        system_prompt = """【导航指令解析规则】
1. 只识别以下位置：A点、B点、充电桩
2. 响应格式：
   - 有效位置：直接返回名称（如"A点"）
   - 无效指令：返回"unknown\""""
        
        user_content = f"{system_prompt}\n用户指令：{text}"
        
        payload = {
            "messages": [
                {"role": "user", "content": user_content}  # 符合百度API要求
            ],
            "temperature": 0.1,  # 合法参数
            "top_p": 0.8
        }
        
        try:
            resp = requests.post(api_url, 
                                headers={"Content-Type": "application/json"},
                                json=payload,
                                timeout=8)
            if resp.status_code != 200:
                rospy.logerr(f"API请求失败 HTTP {resp.status_code}")
                return None
                
            data = resp.json()
            rospy.logdebug(f"API原始响应: {json.dumps(data, ensure_ascii=False)}")
            
            if "error_code" in data:
                rospy.logerr(f"API错误 {data['error_code']}: {data['error_msg']}")
                return None
                
            result = data.get('result', '').strip()
            return result.replace(" ", "").replace("。", "")
        except Exception as e:
            rospy.logerr(f"API请求异常: {str(e)}")
            return None

    def publish_goal(self, location):
        """发布导航目标"""
        # 模糊匹配逻辑
        matched = None
        for key in self.nav_points:
            if key in location:
                matched = key
                break
                
        if not matched:
            rospy.logwarn(f"未知位置：{location}")
            rospy.loginfo(f"已知位置：{list(self.nav_points.keys())}")
            return False
            
        goal = NavGoal()
        goal.location_name = matched
        goal.x = self.nav_points[matched]["x"]
        goal.y = self.nav_points[matched]["y"]
        goal.theta_degrees = self.nav_points[matched]["theta"]
        
        self.nav_pub.publish(goal)
        rospy.loginfo(f"已发布导航目标：{matched}")
        return True

    def process_input(self):
        """输入处理线程"""
        while self.running and not rospy.is_shutdown():
            try:
                cmd = input("\n请输入导航指令 > ").strip()
                if not cmd:
                    continue
                
                if cmd.lower() in ['exit', 'quit']:
                    self.running = False
                    rospy.signal_shutdown("用户退出")
                    break
                
                rospy.loginfo(f"正在解析：{cmd}")
                result = self.parse_command(cmd)
                
                if result == "unknown":
                    rospy.logwarn("未识别到有效位置")
                elif result and result in self.nav_points:
                    self.publish_goal(result)
                elif result:
                    self.publish_goal(result)  # 尝试模糊匹配
                else:
                    rospy.logwarn("解析失败，请重试")
                    
            except (KeyboardInterrupt, EOFError):
                self.running = False
                rospy.signal_shutdown("键盘中断")
                break

    def cleanup(self):
        """资源清理"""
        self.running = False
        if self.input_thread.is_alive():
            self.input_thread.join()
        rospy.loginfo("节点已关闭")

if __name__ == "__main__":
    try:
        node = ErnieNavCommander()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass