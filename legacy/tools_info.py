tools = """
你拥有以下工具：

1. weather
作用：
查询天气

参数：
city 城市名称


2. calculator
作用：
计算两个数字相加

参数：
a 第一个数字
b 第二个数字


如果用户的问题需要工具，
请只返回JSON格式：

天气:
{
 "tool":"weather",
 "city":"北京"
}


计算:
{
 "tool":"calculator",
 "a":3,
 "b":5
}


如果不需要工具，正常回答。
"""