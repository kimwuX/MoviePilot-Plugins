# Tracker自定义编辑

作者：kim.wu
主页：https://github.com/kimwuX

## 1、简介

按照自定义规则批量替换、删除、增加种子 tracker

## 2、使用说明

**提示：关键字尽量长一些，可以减少误判**

### 2.1、新增

```
ADD|现有tracker关键字|新增tracker关键字
```

替换现有 tracker 关键字形成新的 tracker 地址，并添加到 tracker 列表中，不修改现有 tracker 地址，例如：

现有 tracker 列表：

```
http://www.baidu.com/announce.php?passkey=abcd1234
```

编辑规则：

```
ADD|http://www.baidu.com|https://www.google.com
```

最终 tracker 列表：

```
http://www.baidu.com/announce.php?passkey=abcd1234
https://www.google.com/announce.php?passkey=abcd1234
```

### 2.2、删除

```
DEL|现有tracker关键字
```

删除包含关键字的 tracker 地址，例如：

现有 tracker 列表：

```
https://www.baidu.com/announce.php?passkey=abcd1234
https://www.google.com/announce.php?passkey=abcd1234
```

编辑规则：

```
DEL|baidu.com
```

最终 tracker 列表：

```
https://www.google.com/announce.php?passkey=abcd1234
```

### 2.3、修改

```
REP|现有tracker关键字|替换tracker关键字
```

修改现有 tracker 关键字，例如：

现有 tracker 列表：

```
http://www.baidu.com/announce.php?passkey=abcd1234
```

编辑规则：

```
REP|http://www.baidu.com|https://www.google.com
REP|abcd1234|abc123
```

最终 tracker 列表：

```
https://www.google.com/announce.php?passkey=abc123
```
