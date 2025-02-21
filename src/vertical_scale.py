import boto3
import logging
import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Define valid combinations for AWS Fargate (in CPU units and memory in MiB)
valid_combinations = {
    256: [512, 1024, 2048],                  # 256 (.25 vCPU): 512 MiB, 1 GB, 2 GB
    512: [1024, 2048, 3072, 4096],            # 512 (.5 vCPU): 1 GB, 2 GB, 3 GB, 4 GB
    1024: [2048, 3072, 4096, 5120, 6144, 7168, 8192],  # 1024 (1 vCPU): 2 GB to 8 GB options
    2048: list(range(4096, 16385, 1024)),     # 2048 (2 vCPU): 4 GB to 16 GB (1 GB increments)
    4096: list(range(8192, 30721, 1024)),      # 4096 (4 vCPU): 8 GB to 30 GB (1 GB increments)
    8192: list(range(16384, 61441, 4096)),      # 8192 (8 vCPU): 16 GB to 60 GB (4 GB increments)
    16384: list(range(32768, 122881, 8192)),    # 16384 (16 vCPU): 32 GB to 120 GB (8 GB increments)
}

def get_next_cpu_combination(current_cpu, current_memory):
    """
    Always increments to the next CPU level. For the new CPU level:
      - If current_memory is below the minimum allowed, use the minimum.
      - If current_memory is valid and there's a higher valid memory option, select that.
      - Otherwise, keep the current memory if it's valid.
      
    Returns a tuple (new_cpu, new_memory). If there's no higher CPU level, returns (None, None).
    """
    # Sort available CPU levels
    cpu_levels = sorted(valid_combinations.keys())

    # Find the index of the current CPU in the list.
    # If the current CPU is not one of the keys, find the next higher CPU.
    new_cpu = None
    for cpu in cpu_levels:
        if cpu > current_cpu:
            new_cpu = cpu
            break
    if new_cpu is None:
        # No higher CPU level available.
        return None, None

    # Get the list of valid memory values for the new CPU level.
    mem_options = valid_combinations[new_cpu]

    # If the current memory is below the minimum for the new CPU level, select the minimum.
    if current_memory < mem_options[0]:
        new_memory = mem_options[0]
    # If the current memory is already in the list and there is a higher value available, choose that.
    elif current_memory in mem_options:
        idx = mem_options.index(current_memory)
        if idx < len(mem_options) - 1:
            new_memory = mem_options[idx + 1]
        else:
            # Already at the highest memory option for this CPU level; keep the current memory.
            new_memory = current_memory
    # Otherwise, if the current memory is not in the list, try to find the smallest valid option
    # that is greater than the current memory.
    else:
        new_memory = None
        for mem in mem_options:
            if mem > current_memory:
                new_memory = mem
                break
        # If not found, then if current_memory is above the maximum, we stick to the highest option.
        if new_memory is None:
            new_memory = mem_options[-1]

    return new_cpu, new_memory

def get_current_task_definition(cluster_name, service_name):
    ecs_client = boto3.client('ecs')

    # Retrieve the ECS service details to get the task definition ARN
    service_response = ecs_client.describe_services(
        cluster=cluster_name,
        services=[service_name]
    )

    services = service_response.get('services', [])
    if not services:
        raise Exception(f"Service '{service_name}' not found in cluster '{cluster_name}'")

    task_def_arn = services[0].get('taskDefinition')
    if not task_def_arn:
        raise Exception("Task definition ARN not found for the service.")

    # Get the full task definition details
    td_response = ecs_client.describe_task_definition(taskDefinition=task_def_arn)
    return td_response.get('taskDefinition')

def register_updated_task_definition(original_td, new_cpu, new_memory):
    """
    Registers a new revision of the task definition with updated CPU and memory.
    """
    ecs_client = boto3.client('ecs')

    # Keys that are returned in describe_task_definition but cannot be used when registering a new revision
    keys_to_remove = [
        'taskDefinitionArn', 'revision', 'status', 'requiresAttributes',
        'compatibilities', 'registeredAt', 'registeredBy'
    ]

    # Create a copy of the original task definition without the read-only fields
    new_td = {k: v for k, v in original_td.items() if k not in keys_to_remove}

    # Update CPU and memory values (assuming they are defined at the task level)
    if 'cpu' in new_td:
        new_td['cpu'] = str(new_cpu)
    if 'memory' in new_td:
        new_td['memory'] = str(new_memory)

    # Register the new task definition revision
    register_response = ecs_client.register_task_definition(**new_td)
    return register_response.get('taskDefinition')

def update_service_with_new_task_definition(cluster_name, service_name, new_task_def_arn):
    """
    Updates the ECS service to use the new task definition and forces a new deployment.
    """
    ecs_client = boto3.client('ecs')
    update_response = ecs_client.update_service(
        cluster=cluster_name,
        service=service_name,
        taskDefinition=new_task_def_arn,
        forceNewDeployment=True
    )
    return update_response

def tag_service(cluster_name, service_name, tags):
    """
    Adds tags to the specified ECS service.
    
    :param cluster_name: The ECS cluster name.
    :param service_name: The ECS service name.
    :param tags: A list of tags, e.g. [{'key': 'Updated', 'value': 'True'}]
    """
    ecs_client = boto3.client('ecs')

    # Retrieve the service ARN by describing the service
    response = ecs_client.describe_services(
        cluster=cluster_name,
        services=[service_name]
    )
    services = response.get('services', [])
    if not services:
        raise Exception(f"Service '{service_name}' not found in cluster '{cluster_name}'")

    service_arn = services[0].get('serviceArn')
    if not service_arn:
        raise Exception("Service ARN not found.")

    # Tag the service using the tag_resource API
    tag_response = ecs_client.tag_resource(
        resourceArn=service_arn,
        tags=tags
    )
    return tag_response


def lambda_handler(event, context):

    logger.info("Lambda function started")


    cluster_name = event["alarmData"]["configuration"]["metrics"][0]["metricStat"]["metric"]["dimensions"]["ClusterName"]
    service_name = event["alarmData"]["configuration"]["metrics"][0]["metricStat"]["metric"]["dimensions"]["ServiceName"]


    service_tags = [{"key": "CpuIncreasedAt", 'value': datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}]

    try:
        # Step 1: Retrieve the current task definition
        original_td = get_current_task_definition(cluster_name, service_name)
        print(f"Current task definition retrieved: {original_td.get('taskDefinitionArn')}")

        current_cpu = int(original_td["cpu"])
        current_memory = int(original_td["memory"])

        new_cpu, new_memory = get_next_cpu_combination(current_cpu, current_memory)

        # Step 2: Register a new revision with updated CPU and memory values
        new_td = register_updated_task_definition(original_td, new_cpu, new_memory)
        new_task_def_arn = new_td.get('taskDefinitionArn')
        print(f"New task definition registered: {new_task_def_arn}")

        # Step 3: Update the service to use the new task definition
        update_response = update_service_with_new_task_definition(cluster_name, service_name, new_task_def_arn)
        print("Service updated. New deployment triggered.")

        # Step 4: Add the tag to the service
        tag_response = tag_service(cluster_name, service_name, service_tags)
        print("Service tagged successfully.")

    except Exception as e:
        print(f"Error: {e}")