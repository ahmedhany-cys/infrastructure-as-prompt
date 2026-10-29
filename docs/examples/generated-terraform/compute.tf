# Application tier: auto scaling group behind the load balancer.
# Implements REQ-SEC-007, REQ-SEC-005, REQ-AVL-001, REQ-PRF-001.

resource "aws_iam_role" "app" {
  name = "${local.name_prefix}-app"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Session Manager access replaces SSH keys and open administrative ports.
resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Least privilege: read only the RDS-managed secret for this database.
resource "aws_iam_role_policy" "app_read_db_secret" {
  name = "read-database-credentials"
  role = aws_iam_role.app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadRdsManagedSecret"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:rds!db-*"
      Condition = {
        StringEquals = {
          "secretsmanager:ResourceTag/aws:rds:primaryDBInstanceArn" = "arn:aws:rds:${var.aws_region}:${var.aws_account_id}:db:${local.db_identifier}"
        }
      }
    }]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name_prefix}-app"
  role = aws_iam_role.app.name
}

resource "aws_launch_template" "app" {
  name_prefix   = "${local.name_prefix}-app-"
  image_id      = "resolve:ssm:${var.app_ami_ssm_parameter}"
  instance_type = var.instance_type

  iam_instance_profile {
    arn = aws_iam_instance_profile.app.arn
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.app.id]
    delete_on_termination       = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = 16
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  monitoring {
    enabled = true
  }

  # Placeholder application: replace with your own build/deploy process.
  user_data = base64encode(<<-EOT
    #!/bin/bash
    set -euo pipefail
    mkdir -p /opt/app
    echo '{"status":"ok"}' > /opt/app/health
    echo '<h1>Deployed by Infrastructure as Prompt</h1><p>Replace this placeholder with your application.</p>' > /opt/app/index.html
    cat > /etc/systemd/system/placeholder-app.service <<'UNIT'
    [Unit]
    Description=Placeholder application
    After=network-online.target
    [Service]
    ExecStart=/usr/bin/python3 -m http.server 3000 --directory /opt/app
    DynamicUser=yes
    Restart=always
    [Install]
    WantedBy=multi-user.target
    UNIT
    systemctl daemon-reload
    systemctl enable --now placeholder-app
  EOT
  )

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${local.name_prefix}-app"
    }
  }
}

resource "aws_autoscaling_group" "app" {
  name_prefix               = "${local.name_prefix}-app-"
  min_size                  = 2
  max_size                  = 6
  desired_capacity          = 2
  vpc_zone_identifier       = aws_subnet.app[*].id
  target_group_arns         = [aws_lb_target_group.app.arn]
  health_check_type         = "ELB"
  health_check_grace_period = 120

  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
    }
  }

  tag {
    key                 = "Name"
    value               = "${local.name_prefix}-app"
    propagate_at_launch = true
  }
}

resource "aws_autoscaling_policy" "cpu_target" {
  name                   = "cpu-target-tracking"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 60
  }
}
