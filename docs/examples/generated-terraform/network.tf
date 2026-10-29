# Network layout: public + private application + isolated data subnets across two AZs.

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

# Implements REQ-SEC-004: the default security group denies all traffic.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-public-${count.index}"
    Tier = "public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-public"
  }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Application tier: private subnets, outbound internet only through NAT.
resource "aws_subnet" "app" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 10 + count.index)
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "${local.name_prefix}-app-${count.index}"
    Tier = "application"
  }
}

resource "aws_eip" "nat" {
  count  = 1
  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-nat-${count.index}"
  }
}

resource "aws_nat_gateway" "main" {
  count = 1

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${local.name_prefix}-nat-${count.index}"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "app" {
  count = 2

  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index % 1].id
  }

  tags = {
    Name = "${local.name_prefix}-app-${count.index}"
  }
}

resource "aws_route_table_association" "app" {
  count = 2

  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app[count.index].id
}

# Data tier: isolated subnets with no route to the internet (REQ-SEC-001).
resource "aws_subnet" "data" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 20 + count.index)
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "${local.name_prefix}-data-${count.index}"
    Tier = "data"
  }
}

resource "aws_route_table" "data" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-data"
  }
}

resource "aws_route_table_association" "data" {
  count = 2

  subnet_id      = aws_subnet.data[count.index].id
  route_table_id = aws_route_table.data.id
}

# Implements REQ-AUD-002: network flow logs for investigation.
resource "aws_flow_log" "vpc" {
  vpc_id                   = aws_vpc.main.id
  traffic_type             = "ALL"
  log_destination_type     = "s3"
  log_destination          = "${aws_s3_bucket.logs.arn}/vpc-flow-logs/"
  max_aggregation_interval = 600

  depends_on = [aws_s3_bucket_policy.logs]
}
